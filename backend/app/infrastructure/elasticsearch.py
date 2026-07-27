"""文档 segment 到 Elasticsearch 向量索引的基础设施适配。"""

from __future__ import annotations

import asyncio
import inspect
import logging
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
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ScoredDocument:
    document: Document
    score: float | None


@dataclass(frozen=True, slots=True)
class _ParentExpansion:
    rankings: dict[str, list[_ScoredDocument]]
    stages: list[dict[str, Any]]


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

    fused, _ = _reciprocal_rank_fusion_with_diagnostics(
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


def _reciprocal_rank_fusion_with_diagnostics(
    ranked_documents: dict[str, Sequence[_ScoredDocument]],
    *,
    rank_constant: int,
    result_limit: int,
) -> tuple[list[Document], list[dict[str, Any]]]:
    """执行 RRF，并返回最终排名及各通道的融合贡献。"""

    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")
    if result_limit < 1:
        raise ValueError("result_limit must be positive")

    scores: dict[str, float] = {}
    documents: dict[str, Document] = {}
    channel_contributions: dict[
        str,
        dict[str, dict[str, float | int | None]],
    ] = {}
    for channel, ranking in ranked_documents.items():
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
            channel_contributions.setdefault(chunk_id, {})[channel] = {
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
    diagnostics = [
        {
            "rank": rank,
            "chunkId": chunk_id,
            "rrfScore": scores[chunk_id],
            "channels": channel_contributions[chunk_id],
            "textPreview": _text_preview(
                documents[chunk_id].page_content
            ),
        }
        for rank, chunk_id in enumerate(selected_chunk_ids, start=1)
    ]
    return fused, diagnostics


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
    parent_chunk_cache: Any | None = Field(
        default=None,
        exclude=True,
        repr=False,
    )
    _retrieval_stages: dict[str, Any] | None = PrivateAttr(default=None)
    _full_text_recall_stage: list[dict[str, Any]] | None = PrivateAttr(
        default=None
    )
    _vector_recall_stage: list[dict[str, Any]] | None = PrivateAttr(
        default=None
    )
    _full_text_parent_stage: list[dict[str, Any]] | None = PrivateAttr(
        default=None
    )
    _vector_parent_stage: list[dict[str, Any]] | None = PrivateAttr(
        default=None
    )

    @property
    def retrieval_stages(self) -> dict[str, Any] | None:
        """返回最近一次请求按执行阶段组织的检索诊断。"""

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
            self._afull_text_search(query),
            self._avector_search(query),
        )
        return self._fuse(full_text_documents, vector_documents)

    def _full_text_search(self, query: str) -> list[_ScoredDocument]:
        return self._expand_parent_chunks(
            "BM25",
            self._raw_full_text_search(query),
        )

    async def _afull_text_search(
        self,
        query: str,
    ) -> list[_ScoredDocument]:
        documents = await asyncio.to_thread(
            self._raw_full_text_search,
            query,
        )
        return await self._aexpand_parent_chunks("BM25", documents)

    def _raw_full_text_search(
        self,
        query: str,
    ) -> list[_ScoredDocument]:
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
        documents = [
            _ScoredDocument(
                document=_document_from_hit(hit),
                score=_elasticsearch_hit_score(hit),
            )
            for hit in response["hits"]["hits"]
        ]
        self._full_text_recall_stage = _recall_channel_stage(
            documents,
        )
        return documents

    def _vector_search(self, query: str) -> list[_ScoredDocument]:
        results = self.store.similarity_search_with_score(
            query,
            **self._vector_search_kwargs(),
        )
        return self._expand_parent_chunks(
            "VECTOR",
            self._filter_vector_results(results),
        )

    async def _avector_search(
        self,
        query: str,
    ) -> list[_ScoredDocument]:
        results = await self.store.asimilarity_search_with_score(
            query,
            **self._vector_search_kwargs(),
        )
        return await self._aexpand_parent_chunks(
            "VECTOR",
            self._filter_vector_results(results),
        )

    def _filter_vector_results(
        self,
        results: Sequence[tuple[Document, float]],
    ) -> list[_ScoredDocument]:
        filtered = [
            _ScoredDocument(document=document, score=float(score))
            for document, score in results
            if score >= self.options.vector_min_score
        ]
        self._vector_recall_stage = _recall_channel_stage(
            filtered,
        )
        return filtered

    def _vector_search_kwargs(self) -> dict[str, Any]:
        return {
            "k": self.options.candidate_limit,
            "filter": build_document_retrieval_filters(self.scope),
        }

    def _fuse(
        self,
        full_text_documents: Sequence[_ScoredDocument],
        vector_documents: Sequence[_ScoredDocument],
    ) -> list[Document]:
        documents, fusion_stage = _reciprocal_rank_fusion_with_diagnostics(
            {
                "BM25": full_text_documents,
                "VECTOR": vector_documents,
            },
            rank_constant=self.options.rank_constant,
            result_limit=self.options.result_limit,
        )
        self._retrieval_stages = {
            "RECALL": {
                "BM25": self._full_text_recall_stage or [],
                "VECTOR": self._vector_recall_stage or [],
            },
            "PARENT_EXPANSION": {
                "BM25": self._full_text_parent_stage
                or _identity_parent_expansion_stage(
                    full_text_documents
                ),
                "VECTOR": self._vector_parent_stage
                or _identity_parent_expansion_stage(
                    vector_documents
                ),
            },
            "RRF": fusion_stage,
        }
        return documents

    def _expand_parent_chunks(
        self,
        channel: str,
        documents: Sequence[_ScoredDocument],
    ) -> list[_ScoredDocument]:
        references = _ranked_parent_chunk_references(
            {channel: documents}
        )
        if not references:
            self._set_parent_stage(
                channel,
                _identity_parent_expansion_stage(documents),
            )
            return list(documents)
        if self.parent_chunk_cache is None:
            raise RuntimeError("parent chunk cache is not configured")
        parent_texts = self.parent_chunk_cache.load(references)
        if inspect.isawaitable(parent_texts):
            parent_texts = asyncio.run(parent_texts)
        return self._apply_parent_expansion(
            channel,
            documents,
            parent_texts,
        )

    async def _aexpand_parent_chunks(
        self,
        channel: str,
        documents: Sequence[_ScoredDocument],
    ) -> list[_ScoredDocument]:
        references = _ranked_parent_chunk_references(
            {channel: documents}
        )
        if not references:
            self._set_parent_stage(
                channel,
                _identity_parent_expansion_stage(documents),
            )
            return list(documents)
        if self.parent_chunk_cache is None:
            raise RuntimeError("parent chunk cache is not configured")
        parent_texts = self.parent_chunk_cache.load(references)
        if inspect.isawaitable(parent_texts):
            parent_texts = await parent_texts
        return self._apply_parent_expansion(
            channel,
            documents,
            parent_texts,
        )

    def _apply_parent_expansion(
        self,
        channel: str,
        documents: Sequence[_ScoredDocument],
        parent_texts: Any,
    ) -> list[_ScoredDocument]:
        expansion = _replace_ranked_children_with_parents(
            {channel: documents},
            parent_texts=parent_texts,
        )
        self._set_parent_stage(channel, expansion.stages)
        return expansion.rankings[channel]

    def _set_parent_stage(
        self,
        channel: str,
        stage: list[dict[str, Any]],
    ) -> None:
        if channel == "BM25":
            self._full_text_parent_stage = stage
            return
        if channel == "VECTOR":
            self._vector_parent_stage = stage
            return
        raise ValueError(f"unsupported retrieval channel: {channel}")


@dataclass(frozen=True, slots=True)
class DocumentHybridRetrieverFactory:
    """创建绑定单次请求授权范围的自定义 Hybrid Retriever。"""

    client: Any
    store: Any
    index_name: str
    options: DocumentRetrievalOptions
    parent_chunk_cache: Any | None = None

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
            parent_chunk_cache=self.parent_chunk_cache,
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


def _parent_chunk_references(
    documents: Sequence[Document],
) -> tuple[tuple[str, str], ...]:
    references: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for document in documents:
        reference = _parent_chunk_reference(document)
        if reference is None or reference in seen:
            continue
        seen.add(reference)
        references.append(reference)
    return tuple(references)


def _ranked_parent_chunk_references(
    rankings: dict[str, Sequence[_ScoredDocument]],
) -> tuple[tuple[str, str], ...]:
    return _parent_chunk_references(
        [
            item.document
            for ranking in rankings.values()
            for item in ranking
        ]
    )


def _parent_chunk_reference(
    document: Document,
) -> tuple[str, str] | None:
    parent_chunk_id = document.metadata.get("parentChunkId")
    if parent_chunk_id is None:
        return None
    if (
        not isinstance(parent_chunk_id, str)
        or not parent_chunk_id.strip()
    ):
        raise ValueError("retrieved document has invalid parentChunkId")
    return _document_doc_id(document), parent_chunk_id.strip()


def _replace_ranked_children_with_parents(
    rankings: dict[str, Sequence[_ScoredDocument]],
    *,
    parent_texts: Any,
) -> _ParentExpansion:
    if not isinstance(parent_texts, dict):
        raise ValueError("parent chunk loader must return a mapping")

    expanded_rankings: dict[str, list[_ScoredDocument]] = {}
    results: list[dict[str, Any]] = []
    missing_logged: set[tuple[str, str]] = set()

    for channel, ranking in rankings.items():
        expanded: list[_ScoredDocument] = []
        seen_parents: set[tuple[str, str]] = set()
        for original_rank, item in enumerate(ranking, start=1):
            document = item.document
            source_chunk_id = _document_chunk_id(document)
            reference = _parent_chunk_reference(document)
            if reference is None:
                expanded.append(item)
                results.append(
                    _parent_expansion_result_debug(
                        item,
                        rank=len(expanded),
                        source_rank=original_rank,
                        source_chunk_id=source_chunk_id,
                    )
                )
                continue

            parent_text = parent_texts.get(reference)
            if (
                not isinstance(parent_text, str)
                or not parent_text.strip()
            ):
                if reference not in missing_logged:
                    missing_logged.add(reference)
                    logger.warning(
                        "parent chunk not found: doc_id=%s, "
                        "parent_chunk_id=%s",
                        reference[0],
                        reference[1],
                    )
                continue
            if reference in seen_parents:
                continue
            seen_parents.add(reference)

            metadata = dict(document.metadata)
            metadata["matchedChunkId"] = source_chunk_id
            metadata["chunkId"] = reference[1]
            expanded_item = _ScoredDocument(
                document=Document(
                    page_content=parent_text,
                    metadata=metadata,
                ),
                score=item.score,
            )
            expanded.append(expanded_item)
            results.append(
                _parent_expansion_result_debug(
                    expanded_item,
                    rank=len(expanded),
                    source_rank=original_rank,
                    source_chunk_id=source_chunk_id,
                )
            )
        expanded_rankings[channel] = expanded

    return _ParentExpansion(
        rankings=expanded_rankings,
        stages=results,
    )


def _recall_channel_stage(
    ranking: Sequence[_ScoredDocument],
) -> list[dict[str, Any]]:
    return [
        _ranked_document_debug(item, rank)
        for rank, item in enumerate(ranking, start=1)
    ]


def _identity_parent_expansion_stage(
    ranking: Sequence[_ScoredDocument],
) -> list[dict[str, Any]]:
    return [
        _parent_expansion_result_debug(
            item,
            rank=rank,
            source_rank=rank,
            source_chunk_id=_document_chunk_id(item.document),
        )
        for rank, item in enumerate(ranking, start=1)
    ]


def _parent_expansion_result_debug(
    item: _ScoredDocument,
    *,
    rank: int,
    source_rank: int,
    source_chunk_id: str,
) -> dict[str, Any]:
    document = item.document
    result = {
        "rank": rank,
        "sourceRank": source_rank,
        "chunkId": _document_chunk_id(document),
        "score": item.score,
        "textPreview": _text_preview(document.page_content),
    }
    if source_chunk_id != result["chunkId"]:
        result["fromChunkId"] = source_chunk_id
    return result


def _ranked_document_debug(
    item: _ScoredDocument,
    rank: int,
) -> dict[str, Any]:
    document = item.document
    result = {
        "rank": rank,
        "chunkId": _document_chunk_id(document),
        "score": item.score,
        "textPreview": _text_preview(document.page_content),
    }
    parent_chunk_id = document.metadata.get("parentChunkId")
    if parent_chunk_id is not None:
        result["parentChunkId"] = parent_chunk_id
    return result


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
