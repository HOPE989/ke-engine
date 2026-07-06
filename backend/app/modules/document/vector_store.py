"""文档 segment 到 Elasticsearch 向量索引的适配层。

该模块负责把数据库里的 `KnowledgeSegment` 转换为 LangChain `Document`，并屏蔽
`langchain-openai` / `langchain-elasticsearch` 的构造细节。业务 workflow 只关心：
- 输入一批 embeddable segment；
- 得到 Elasticsearch 返回的向量文档 ID；
- 失败时能按返回 ID 或 `metadata.docId` 做补偿清理。

注意：这里不生成确定性向量 ID，而是保留 Elasticsearch/LangChain 返回的 ID，并由
repository 写回 `knowledge_segment.embedding_id`。
"""

from __future__ import annotations

import inspect
from typing import Any

from elasticsearch import NotFoundError
from langchain_core.documents import Document
from langchain_elasticsearch import ElasticsearchStore
from langchain_openai import OpenAIEmbeddings


EMBEDDING_MODEL = "text-embedding-v4"
EMBEDDING_CHUNK_SIZE = 9
VECTOR_FIELD = "vector"
TEXT_FIELD = "text"


class VectorStoreIdCountMismatch(Exception):
    """Elasticsearch 返回的 ID 数量与输入 segment 数量不一致。

    `returned_ids` 保存本轮已经拿到的 ID，workflow 捕获后会优先按这些 ID 做精确清理，
    再按 `docId` 兜底清理。
    """

    def __init__(self, *, returned_ids: list[str] | None = None) -> None:
        self.returned_ids = list(returned_ids or [])
        super().__init__("vector store returned ID count mismatch")


class VectorIndexDimensionMismatch(Exception):
    """现有 Elasticsearch 向量索引维度与配置的 embedding 维度不一致。"""


def create_embedding_model(settings: Any) -> OpenAIEmbeddings:
    """创建向量存储专用的 OpenAI-compatible embedding model。

    这里固定模型为 `text-embedding-v4`，固定 LangChain 请求批大小为 `9`，并关闭
    native tokenizer 上下文长度检查。维度来自运行时配置，必须与 Elasticsearch mapping
    中的 dense_vector 维度保持一致。
    """

    return OpenAIEmbeddings(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=EMBEDDING_MODEL,
        chunk_size=EMBEDDING_CHUNK_SIZE,
        dimensions=settings.embedding_dimensions,
        check_embedding_ctx_length=False,
    )


def create_elasticsearch_store(
    *,
    settings: Any,
    embedding_model: Any,
) -> ElasticsearchStore:
    """创建 LangChain ElasticsearchStore。

    `query_field` 存放原文 segment 文本，`vector_query_field` 存放 dense vector。
    `num_dimensions` 显式传入，便于 LangChain 创建/校验索引时使用配置维度。
    """

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
    """创建或校验 Elasticsearch 向量索引。

    若索引不存在，则创建最小可用 mapping：`text` 用于 page content，`vector` 用于
    dense vector，`metadata` 保留 docId/chunkId 等后续过滤字段。若索引已存在，则只
    校验向量维度，避免 worker 在错误 mapping 上继续写入不可检索的数据。
    """

    if not client.indices.exists(index=index_name):
        # 首次部署或空测试环境下创建最小 mapping；不在这里实现检索相关配置。
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

    # 已存在索引时只读取 vector 字段维度；不修改现有 mapping，避免隐式迁移线上索引。
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
    """把持久化 segment 转换为 LangChain vector-store 调用。

    Adapter 的职责是保持输入 segment 顺序和返回 ID 顺序一一对应，并提供失败补偿需要的
    删除能力。它不直接依赖数据库，也不决定哪些 segment 应该被处理。
    """

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
        """写入一批 segment，并按输入顺序返回 Elasticsearch 文档 ID。

        `segment.text` 只写入 `Document.page_content`，`segment.metadata_` 只写入
        `Document.metadata`，避免把正文重复塞进 metadata。
        """

        # LangChain 的 Document 是 vector store 的稳定边界：正文和 metadata 必须分离。
        documents = [
            Document(
                page_content=segment.text,
                metadata=_segment_metadata(segment),
            )
            for segment in segments
        ]
        ids = await self._store.aadd_documents(documents)
        if len(ids) != len(segments):
            # 数量不一致会破坏 segment -> embedding_id 对应关系，必须让整个事务失败。
            raise VectorStoreIdCountMismatch(returned_ids=ids)
        return ids

    async def delete_by_ids(self, ids: list[str]) -> None:
        """按 Elasticsearch 文档 ID 删除向量文档，用于失败后的精确补偿。"""

        if not ids:
            return
        await self._store.adelete(ids=ids)

    async def delete_by_doc_id(self, doc_id: int) -> None:
        """按 `metadata.docId` 删除一个文档的全部向量文档。

        这是重试前清理和失败兜底清理使用的粗粒度补偿。adapter 允许未注入 client/index，
        主要方便单元测试或只需要写入能力的调用方。
        """

        if self._client is None or self._index_name is None:
            return
        try:
            # delete_by_query 可能来自同步或异步 ES client；下面统一兼容两种返回值。
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
    """读取 SQLAlchemy 模型或测试替身上的 metadata 字段并复制一份。

    SQLAlchemy 模型把数据库列 `metadata` 映射为 `metadata_`，测试替身可能直接使用
    `metadata`。返回副本避免 LangChain 或调用方意外修改 ORM 对象上的原始 dict。
    """

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
