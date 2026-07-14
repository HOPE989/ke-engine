"""文档 segment 到 Elasticsearch 向量索引的基础设施适配。"""

from __future__ import annotations

import inspect
from typing import Any

from elasticsearch import NotFoundError
from langchain_core.documents import Document
from langchain_elasticsearch import ElasticsearchStore

VECTOR_FIELD = "vector"
TEXT_FIELD = "text"


class VectorStoreIdCountMismatch(Exception):
    """Elasticsearch 返回的 ID 数量与输入 segment 数量不一致。"""

    def __init__(self, *, returned_ids: list[str] | None = None) -> None:
        self.returned_ids = list(returned_ids or [])
        super().__init__("vector store returned ID count mismatch")


class VectorIndexDimensionMismatch(Exception):
    """现有 Elasticsearch 向量索引维度与配置的 embedding 维度不一致。"""


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
                    "metadata": {"type": "object", "enabled": True},
                }
            },
        )
        return

    mapping = client.indices.get_mapping(index=index_name)
    dimensions = (
        mapping.get(index_name, {})
        .get("mappings", {})
        .get("properties", {})
        .get(VECTOR_FIELD, {})
        .get("dims")
    )
    if dimensions != embedding_dimensions:
        raise VectorIndexDimensionMismatch()


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


def _is_index_not_found_error(exc: NotFoundError) -> bool:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return error.get("type") == "index_not_found_exception"
        if isinstance(error, str):
            return error == "index_not_found_exception"
    return "index_not_found_exception" in str(exc)
