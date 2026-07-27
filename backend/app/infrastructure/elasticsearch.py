"""文档 segment 到 Elasticsearch 向量索引的基础设施适配。"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Sequence

from elasticsearch import Elasticsearch, NotFoundError
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_elasticsearch import DenseVectorStrategy, ElasticsearchStore
from pydantic import ConfigDict, Field, PrivateAttr
from typing_extensions import override

from app.domains.rag.graph.retrieval import (
    DocumentRetrievalOptions,
    DocumentRetrievalScope,
)

VECTOR_FIELD = "vector"
TEXT_FIELD = "text"
_TEXT_PREVIEW_LIMIT = 200


@dataclass(frozen=True, slots=True)
class _ScoredDocument:
    document: Document
    score: float | None


class VectorStoreIdCountMismatch(Exception):
    """Elasticsearch 返回的 ID 数量与输入 segment 数量不一致。"""

    def __init__(self, *, returned_ids: list[str] | None = None) -> None:
        self.returned_ids = list(returned_ids or [])
        super().__init__("vector store returned ID count mismatch")


class VectorIndexDimensionMismatch(Exception):
    """现有 Elasticsearch 向量索引维度与配置的 embedding 维度不一致。"""


class VectorIndexMappingMismatch(Exception):
    """现有 Elasticsearch 索引不能安全支持文档混合检索。"""

    def __init__(self, field_path: str) -> None:
        self.field_path = field_path
        super().__init__(
            f"incompatible Elasticsearch mapping: {field_path}"
        )


def create_elasticsearch_client(settings: Any) -> Elasticsearch:
    """创建供 mapping 校验与 LangChain Store 共享的 ES client。"""

    return Elasticsearch(settings.elasticsearch_url)


def create_elasticsearch_store(
    *,
    settings: Any,
    embedding_model: Any,
) -> ElasticsearchStore:
    """创建 LangChain ElasticsearchStore。"""

    return ElasticsearchStore(
        index_name=settings.elasticsearch_index,
        es_url=settings.elasticsearch_url,
        embedding=embedding_model,
        query_field=TEXT_FIELD,
        vector_query_field=VECTOR_FIELD,
        num_dimensions=settings.embedding_dimensions,
        metadata_mappings={
            "docId": {"type": "keyword"},
            "chunkId": {"type": "keyword"},
            "accessibleBy": {"type": "keyword"},
        },
    )


def create_document_retrieval_store(
    *,
    settings: Any,
    embedding_model: Any,
    client: Any | None = None,
) -> ElasticsearchStore:
    """创建仅负责 KNN 的 LangChain ElasticsearchStore。"""

    connection = (
        {"client": client}
        if client is not None
        else {"es_url": settings.elasticsearch_url}
    )
    return ElasticsearchStore(
        index_name=settings.elasticsearch_index,
        embedding=embedding_model,
        query_field=TEXT_FIELD,
        vector_query_field=VECTOR_FIELD,
        num_dimensions=settings.embedding_dimensions,
        strategy=DenseVectorStrategy(hybrid=False),
        **connection,
    )


def build_document_retrieval_filters(
    scope: DocumentRetrievalScope,
) -> list[dict[str, Any]]:
    """把已验证的服务端 scope 转为 BM25/KNN 共用的 ES filters。"""

    filters: list[dict[str, Any]] = [
        {
            "terms": {
                "metadata.accessibleBy": list(scope.accessible_by),
            }
        }
    ]
    if scope.doc_ids:
        filters.append(
            {"terms": {"metadata.docId": list(scope.doc_ids)}}
        )
    return filters


def reciprocal_rank_fusion(
    ranked_documents: Sequence[Sequence[Document]],
    *,
    rank_constant: int,
    result_limit: int,
) -> list[Document]:
    """按稳定 chunkId 对多个排序列表执行确定性 RRF。"""

    fused, _ = _reciprocal_rank_fusion_with_stages(
        {
            f"RANKING_{index}": [
                _ScoredDocument(document=document, score=None)
                for document in ranking
            ]
            for index, ranking in enumerate(ranked_documents)
        },
        rank_constant=rank_constant,
        result_limit=result_limit,
    )
    return fused


def _reciprocal_rank_fusion_with_stages(
    ranked_documents: dict[str, Sequence[_ScoredDocument]],
    *,
    rank_constant: int,
    result_limit: int,
) -> tuple[list[Document], dict[str, Any]]:
    """执行 RRF，并保留每个通道的原始排名、分数和融合贡献。"""

    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")
    if result_limit < 1:
        raise ValueError("result_limit must be positive")

    scores: dict[str, float] = {}
    documents: dict[str, Document] = {}
    contributions: dict[str, dict[str, dict[str, float | int | None]]] = {}
    stages: dict[str, Any] = {}
    for channel, ranking in ranked_documents.items():
        stages[channel] = {
            "resultCount": len(ranking),
            "scoreType": (
                "ELASTICSEARCH_BM25"
                if channel == "BM25"
                else "ELASTICSEARCH_KNN"
                if channel == "VECTOR"
                else "UNSPECIFIED"
            ),
            "ranking": [
                _ranked_document_debug(item, rank)
                for rank, item in enumerate(ranking, start=1)
            ],
        }
        seen: set[str] = set()
        for rank, item in enumerate(ranking, start=1):
            document = item.document
            chunk_id = _document_chunk_id(document)
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            documents.setdefault(chunk_id, document)
            contribution = 1.0 / (rank_constant + rank)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + contribution
            contributions.setdefault(chunk_id, {})[channel] = {
                "rank": rank,
                "score": item.score,
                "rrfContribution": contribution,
            }

    ordered_chunk_ids = sorted(
        scores,
        key=lambda chunk_id: (-scores[chunk_id], chunk_id),
    )
    selected_chunk_ids = ordered_chunk_ids[:result_limit]
    fused = [
        documents[chunk_id]
        for chunk_id in selected_chunk_ids
    ]
    stages["RRF"] = {
        "resultCount": len(fused),
        "rankConstant": rank_constant,
        "ranking": [
            {
                "rank": rank,
                "chunkId": chunk_id,
                "docId": _document_doc_id(documents[chunk_id]),
                "rrfScore": scores[chunk_id],
                "channels": contributions[chunk_id],
                "textPreview": _text_preview(
                    documents[chunk_id].page_content
                ),
            }
            for rank, chunk_id in enumerate(selected_chunk_ids, start=1)
        ],
    }
    return fused, stages


class ElasticsearchHybridRetriever(BaseRetriever):
    """并行执行 Elasticsearch BM25/KNN 并在应用层 RRF。"""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        frozen=True,
    )

    client: Any = Field(exclude=True, repr=False)
    store: Any = Field(exclude=True, repr=False)
    index_name: str
    scope: DocumentRetrievalScope
    options: DocumentRetrievalOptions
    _retrieval_stages: dict[str, Any] | None = PrivateAttr(default=None)

    @property
    def retrieval_stages(self) -> dict[str, Any] | None:
        """返回最近一次请求的两路召回与 RRF 排名诊断。"""

        return self._retrieval_stages

    @override
    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Any,
    ) -> list[Document]:
        del run_manager
        full_text_documents = self._full_text_search(query)
        vector_documents = self._vector_search(query)
        return self._fuse(full_text_documents, vector_documents)

    @override
    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Any,
    ) -> list[Document]:
        del run_manager
        full_text_documents, vector_documents = await asyncio.gather(
            asyncio.to_thread(self._full_text_search, query),
            self._avector_search(query),
        )
        return self._fuse(full_text_documents, vector_documents)

    def _full_text_search(self, query: str) -> list[_ScoredDocument]:
        filters = build_document_retrieval_filters(self.scope)
        response = self.client.search(
            index=self.index_name,
            size=self.options.candidate_limit,
            query={
                "bool": {
                    "must": [
                        {
                            "match": {
                                TEXT_FIELD: {
                                    "query": query,
                                }
                            }
                        }
                    ],
                    "filter": filters,
                }
            },
        )
        return [
            _ScoredDocument(
                document=_document_from_hit(hit),
                score=_elasticsearch_hit_score(hit),
            )
            for hit in response["hits"]["hits"]
        ]

    def _vector_search(self, query: str) -> list[_ScoredDocument]:
        return [
            _ScoredDocument(document=document, score=float(score))
            for document, score in self.store.similarity_search_with_score(
                query,
                **self._vector_search_kwargs(),
            )
        ]

    async def _avector_search(
        self,
        query: str,
    ) -> list[_ScoredDocument]:
        results = await self.store.asimilarity_search_with_score(
            query,
            **self._vector_search_kwargs(),
        )
        return [
            _ScoredDocument(document=document, score=float(score))
            for document, score in results
        ]

    def _vector_search_kwargs(self) -> dict[str, Any]:
        return {
            "k": self.options.candidate_limit,
            "fetch_k": self.options.candidate_limit,
            "filter": build_document_retrieval_filters(self.scope),
        }

    def _fuse(
        self,
        full_text_documents: Sequence[_ScoredDocument],
        vector_documents: Sequence[_ScoredDocument],
    ) -> list[Document]:
        documents, stages = _reciprocal_rank_fusion_with_stages(
            {
                "BM25": full_text_documents,
                "VECTOR": vector_documents,
            },
            rank_constant=self.options.rank_constant,
            result_limit=self.options.result_limit,
        )
        self._retrieval_stages = stages
        return documents


@dataclass(frozen=True, slots=True)
class DocumentHybridRetrieverFactory:
    """创建绑定单次请求授权范围的自定义 Hybrid Retriever。"""

    client: Any
    store: Any
    index_name: str
    options: DocumentRetrievalOptions

    def create(
        self,
        scope: DocumentRetrievalScope,
    ) -> ElasticsearchHybridRetriever:
        return ElasticsearchHybridRetriever(
            client=self.client,
            store=self.store,
            index_name=self.index_name,
            scope=scope,
            options=self.options,
        )


def ensure_vector_index(
    client: Any,
    *,
    index_name: str,
    embedding_dimensions: int,
) -> None:
    """创建或校验 Elasticsearch 向量索引。"""

    if not client.indices.exists(index=index_name):
        client.indices.create(
            index=index_name,
            mappings={
                "properties": {
                    TEXT_FIELD: {"type": "text"},
                    VECTOR_FIELD: {"type": "dense_vector", "dims": embedding_dimensions},
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "docId": {"type": "keyword"},
                            "chunkId": {"type": "keyword"},
                            "accessibleBy": {"type": "keyword"},
                        },
                    },
                }
            },
        )
        return

    mapping = client.indices.get_mapping(index=index_name)
    properties = (
        mapping.get(index_name, {})
        .get("mappings", {})
        .get("properties", {})
    )
    _require_mapping_type(properties, VECTOR_FIELD, "dense_vector")
    dimensions = properties.get(VECTOR_FIELD, {}).get("dims")
    if dimensions != embedding_dimensions:
        raise VectorIndexDimensionMismatch()
    _require_mapping_type(properties, TEXT_FIELD, "text")
    metadata = properties.get("metadata", {})
    metadata_type = metadata.get("type")
    metadata_properties = metadata.get("properties")
    if (
        metadata_type not in (None, "object")
        or not isinstance(metadata_properties, dict)
    ):
        raise VectorIndexMappingMismatch("metadata")
    for field_name in ("docId", "chunkId", "accessibleBy"):
        _require_mapping_type(
            metadata_properties,
            field_name,
            "keyword",
            path_prefix="metadata.",
        )


class ElasticsearchVectorStoreAdapter:
    """把持久化 segment 转换为 LangChain vector-store 调用。"""

    def __init__(
        self,
        *,
        store: Any,
        client: Any | None = None,
        index_name: str | None = None,
    ) -> None:
        self._store = store
        self._client = client
        self._index_name = index_name

    async def add_segments(self, segments: list[Any]) -> list[str]:
        """写入一批 segment，并按输入顺序返回 Elasticsearch 文档 ID。"""

        documents = [
            Document(
                page_content=segment.text,
                metadata=_segment_metadata(segment),
            )
            for segment in segments
        ]
        ids = await self._store.aadd_documents(documents)
        if len(ids) != len(segments):
            raise VectorStoreIdCountMismatch(returned_ids=ids)
        return ids

    async def delete_by_ids(self, ids: list[str]) -> None:
        """按 Elasticsearch 文档 ID 删除向量文档。"""

        if not ids:
            return
        await self._store.adelete(ids=ids)

    async def delete_by_doc_id(self, doc_id: int) -> None:
        """按 `metadata.docId` 删除一个文档的全部向量文档。"""

        if self._client is None or self._index_name is None:
            return
        try:
            result = self._client.delete_by_query(
                index=self._index_name,
                query={"term": {"metadata.docId": str(doc_id)}},
                conflicts="proceed",
                refresh=True,
            )
            if inspect.isawaitable(result):
                await result
        except NotFoundError as exc:
            if _is_index_not_found_error(exc):
                return
            raise


def _segment_metadata(segment: Any) -> dict[str, Any]:
    metadata = getattr(segment, "metadata_", None)
    if metadata is None:
        metadata = getattr(segment, "metadata", {})
    return dict(metadata)


def _ranked_document_debug(
    item: _ScoredDocument,
    rank: int,
) -> dict[str, Any]:
    document = item.document
    return {
        "rank": rank,
        "chunkId": _document_chunk_id(document),
        "docId": _document_doc_id(document),
        "score": item.score,
        "textPreview": _text_preview(document.page_content),
    }


def _elasticsearch_hit_score(hit: dict[str, Any]) -> float | None:
    score = hit.get("_score")
    if score is None:
        return None
    if not isinstance(score, (int, float)):
        raise ValueError("Elasticsearch hit has invalid _score")
    return float(score)


def _document_doc_id(document: Document) -> str:
    doc_id = document.metadata.get("docId")
    if not isinstance(doc_id, str) or not doc_id.strip():
        raise ValueError("retrieved document missing docId")
    return doc_id.strip()


def _document_chunk_id(document: Document) -> str:
    chunk_id = document.metadata.get("chunkId")
    if not isinstance(chunk_id, str) or not chunk_id.strip():
        raise ValueError("retrieved document missing chunkId")
    return chunk_id.strip()


def _text_preview(text: str) -> str:
    return text[:_TEXT_PREVIEW_LIMIT]


def _document_from_hit(hit: dict[str, Any]) -> Document:
    source = hit.get("_source")
    if not isinstance(source, dict):
        raise ValueError("Elasticsearch hit missing _source")
    text = source.get(TEXT_FIELD)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Elasticsearch hit missing text")
    metadata = source.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Elasticsearch hit missing metadata")
    return Document(
        page_content=text,
        metadata=dict(metadata),
    )


def _require_mapping_type(
    properties: dict[str, Any],
    field_name: str,
    expected_type: str,
    *,
    path_prefix: str = "",
) -> None:
    if properties.get(field_name, {}).get("type") != expected_type:
        raise VectorIndexMappingMismatch(f"{path_prefix}{field_name}")


def _is_index_not_found_error(exc: NotFoundError) -> bool:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return error.get("type") == "index_not_found_exception"
        if isinstance(error, str):
            return error == "index_not_found_exception"
    return "index_not_found_exception" in str(exc)
