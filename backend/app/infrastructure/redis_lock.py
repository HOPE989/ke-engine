"""Redis 客户端和文档转换锁工厂。"""

from typing import Any

import redis
import redis_lock


def create_redis_client(redis_url: str) -> redis.Redis:
    """按 URL 创建 redis-py 客户端。"""

    return redis.Redis.from_url(redis_url)


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
