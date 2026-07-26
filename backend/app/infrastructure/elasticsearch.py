"""文档 segment 到 Elasticsearch 向量索引的基础设施适配。"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from elasticsearch import Elasticsearch, NotFoundError
from langchain_core.documents import Document
from langchain_elasticsearch import DenseVectorStrategy, ElasticsearchStore

from app.domains.rag.graph.retrieval import (
    DocumentRetrievalOptions,
    DocumentRetrievalScope,
)

VECTOR_FIELD = "vector"
TEXT_FIELD = "text"


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
    )


def create_hybrid_elasticsearch_store(
    *,
    settings: Any,
    embedding_model: Any,
    options: DocumentRetrievalOptions,
    client: Any | None = None,
) -> ElasticsearchStore:
    """创建复用原生 BM25/KNN/RRF 的 LangChain ElasticsearchStore。"""

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
        strategy=DenseVectorStrategy(
            hybrid=True,
            rrf={
                "rank_constant": options.rank_constant,
                "rank_window_size": options.rank_window_size,
            },
            text_field=TEXT_FIELD,
        ),
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


@dataclass(frozen=True, slots=True)
class DocumentHybridRetrieverFactory:
    """从共享 Store 创建绑定单次请求授权范围的 Retriever。"""

    store: Any
    options: DocumentRetrievalOptions

    def create(self, scope: DocumentRetrievalScope) -> Any:
        return self.store.as_retriever(
            search_kwargs={
                "k": self.options.result_limit,
                "fetch_k": self.options.rank_window_size,
                "filter": build_document_retrieval_filters(scope),
            }
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
    if metadata.get("type") != "object":
        raise VectorIndexMappingMismatch("metadata")
    metadata_properties = metadata.get("properties", {})
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
