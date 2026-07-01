"""文档对象存储 key、URL 和 MinIO 适配器。"""

from dataclasses import dataclass
from io import BytesIO
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.modules.document.schemas import safe_upload_basename


def original_object_key(*, doc_id: int, safe_filename: str) -> str:
    """生成原始上传文件的对象 key。"""

    return f"documents/{doc_id}/original/{safe_filename}"


def converted_markdown_object_key(*, doc_id: int) -> str:
    """生成转换后 Markdown 的固定对象 key。"""

    return f"documents/{doc_id}/converted/document.md"


def asset_object_key(*, doc_id: int, image_filename: str) -> str:
    """生成 PDF 转换图片资源的对象 key。"""

    # 图片文件名再次走 basename 校验，避免 ZIP 内路径污染对象 key。
    return f"documents/{doc_id}/assets/{safe_upload_basename(image_filename)}"


def public_object_url(*, public_base_url: str, bucket: str, object_key: str) -> str:
    """根据公开 base URL、bucket 和对象 key 拼出稳定 URL。"""

    return f"{public_base_url.rstrip('/')}/{bucket}/{object_key}"


@dataclass(frozen=True, slots=True)
class DocumentObjectStorage:
    """围绕同步 MinIO SDK 的异步文档对象存储适配器。"""

    client: Any
    bucket: str
    public_base_url: str

    async def ensure_bucket(self) -> None:
        """确保目标 bucket 存在。"""

        # MinIO Python SDK 是同步 API，必须放到线程池避免阻塞事件循环。
        bucket_exists = await run_in_threadpool(self.client.bucket_exists, self.bucket)
        if not bucket_exists:
            await run_in_threadpool(self.client.make_bucket, self.bucket)

    async def upload_bytes(
        self,
        *,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> str:
        """上传字节内容并返回稳定公开 URL。"""

        await run_in_threadpool(
            self.client.put_object,
            self.bucket,
            object_key,
            BytesIO(content),
            len(content),
            content_type=content_type,
        )
        return public_object_url(
            public_base_url=self.public_base_url,
            bucket=self.bucket,
            object_key=object_key,
        )
