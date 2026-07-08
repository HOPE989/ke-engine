"""Elasticsearch 基础设施入口。"""

from app.domains.document.components.vector_store import (
    ElasticsearchVectorStoreAdapter,
    create_elasticsearch_store,
    ensure_vector_index,
)

__all__ = [
    "ElasticsearchVectorStoreAdapter",
    "create_elasticsearch_store",
    "ensure_vector_index",
]
