"""MinIO SDK client 的项目级访问器。"""

from functools import lru_cache

from minio import Minio

from app.core.config import get_settings


@lru_cache
def get_minio_client() -> Minio:
    """创建并缓存 MinIO client。"""

    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
