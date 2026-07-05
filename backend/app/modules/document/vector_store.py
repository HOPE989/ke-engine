"""Elasticsearch vector-store adapter for document segments."""

from __future__ import annotations

import inspect
from typing import Any

from langchain_core.documents import Document
from langchain_elasticsearch import ElasticsearchStore
from langchain_openai import OpenAIEmbeddings


EMBEDDING_MODEL = "text-embedding-v4"
EMBEDDING_CHUNK_SIZE = 9
VECTOR_FIELD = "vector"
TEXT_FIELD = "text"


class VectorStoreIdCountMismatch(Exception):
    """Raised when Elasticsearch returns a different ID count than stored segments."""

    def __init__(self, *, returned_ids: list[str] | None = None) -> None:
        self.returned_ids = list(returned_ids or [])
        super().__init__("vector store returned ID count mismatch")


class VectorIndexDimensionMismatch(Exception):
    """Raised when an existing vector index has incompatible dimensions."""


def create_embedding_model(settings: Any) -> OpenAIEmbeddings:
    """Create the OpenAI-compatible embedding model used by vector storage."""

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
    """Create the LangChain Elasticsearch store with the configured index."""

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
    """Create or validate the vector index dimensions."""

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
    """Translate persisted document segments to LangChain vector-store calls."""

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
        """Add embeddable segments and return vector-store IDs in input order."""

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
        """Delete vectors by Elasticsearch document IDs."""

        if not ids:
            return
        await self._store.adelete(ids=ids)

    async def delete_by_doc_id(self, doc_id: int) -> None:
        """Delete vectors for one document by metadata docId."""

        if self._client is None or self._index_name is None:
            return
        result = self._client.delete_by_query(
            index=self._index_name,
            query={"term": {"metadata.docId": str(doc_id)}},
            conflicts="proceed",
            refresh=True,
        )
        if inspect.isawaitable(result):
            await result


def _segment_metadata(segment: Any) -> dict[str, Any]:
    metadata = getattr(segment, "metadata_", None)
    if metadata is None:
        metadata = getattr(segment, "metadata", {})
    return dict(metadata)
