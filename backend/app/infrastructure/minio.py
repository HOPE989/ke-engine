"""MinIO SDK client 的项目级访问器。"""

import json
from functools import lru_cache
from typing import Any

from minio import Minio
from starlette.concurrency import run_in_threadpool

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


async def ensure_minio_bucket(client: Any, bucket: str) -> None:
    """确保 MinIO bucket 存在，并允许对象 URL 匿名读取。"""

    bucket_exists = await run_in_threadpool(client.bucket_exists, bucket)
    if not bucket_exists:
        await run_in_threadpool(client.make_bucket, bucket)
    await run_in_threadpool(client.set_bucket_policy, bucket, public_read_bucket_policy(bucket))


def public_read_bucket_policy(bucket: str) -> str:
    """生成只允许匿名读取对象的 bucket policy。"""

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": ["*"]},
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
            }
        ],
    }
    return json.dumps(policy, separators=(",", ":"))
