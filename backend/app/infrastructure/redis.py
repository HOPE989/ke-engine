"""Redis client 与文档流程分布式锁工厂。"""

from typing import Any

import redis
import redis_lock


def create_redis_client(redis_url: str) -> redis.Redis:
    """按 URL 创建 redis-py client。"""

    return redis.Redis.from_url(redis_url)


def chat_completion_lock(
    *,
    redis_client: Any,
    conversation_id: int,
    expire_seconds: int,
):
    """创建覆盖整次 Chat completion 的 conversation 级锁。"""

    return redis_lock.Lock(
        redis_client,
        name=f"chat:conversation:{conversation_id}:completion",
        expire=expire_seconds,
        auto_renewal=True,
    )


def document_conversion_lock(
    *,
    redis_client: Any,
    doc_id: int,
    expire_seconds: int,
):
    """创建单文档转换锁。"""

    return redis_lock.Lock(
        redis_client,
        name=f"document:{doc_id}:convert",
        expire=expire_seconds,
        auto_renewal=True,
    )


def document_chunking_lock(
    *,
    redis_client: Any,
    doc_id: int,
    expire_seconds: int,
):
    """创建单文档切分锁。"""

    return redis_lock.Lock(
        redis_client,
        name=f"document:{doc_id}:chunk",
        expire=expire_seconds,
        auto_renewal=True,
    )


def data_query_upload_lock(
    *,
    redis_client: Any,
    namespace: str,
    expire_seconds: int,
):
    """创建 DATA_QUERY 上传 namespace 锁。"""

    return redis_lock.Lock(
        redis_client,
        name=f"data_query_upload:{namespace}",
        expire=expire_seconds,
        auto_renewal=True,
    )


def document_embed_store_lock(
    *,
    redis_client: Any,
    doc_id: int,
    expire_seconds: int,
):
    """创建单文档向量存储锁。"""

    return redis_lock.Lock(
        redis_client,
        name=f"document:{doc_id}:embed-store",
        expire=expire_seconds,
        auto_renewal=True,
    )
