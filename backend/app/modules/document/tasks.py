"""文档转换 Celery 任务。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import get_settings
from app.infrastructure.celery import celery_app


class CeleryDocumentConversionDispatcher:
    """把文档解析任务投递给 Celery。"""

    def dispatch(self, doc_id: int) -> None:
        """异步投递单文档解析任务。"""

        convert_document.apply_async(args=(doc_id,))


@celery_app.task(name="document.convert")
def convert_document(doc_id: int) -> None:
    """Celery 入口：解析单个已上传文档。"""

    asyncio.run(_run_document_conversion(doc_id=int(doc_id)))


async def _run_document_conversion(doc_id: int) -> None:
    """为 worker 单次任务按需创建运行时资源并执行解析。"""

    from app.infrastructure.redis_lock import create_redis_client, document_conversion_lock

    settings = get_settings()
    redis_client = create_redis_client(settings.redis_url)
    try:
        lock = document_conversion_lock(
            redis_client=redis_client,
            doc_id=doc_id,
            expire_seconds=settings.document_convert_lock_expire_seconds,
        )
        if not lock.acquire(blocking=False):
            return
        try:
            await _run_locked_document_conversion(doc_id=doc_id, settings=settings)
        finally:
            lock.release()
    finally:
        redis_client.close()


async def _run_locked_document_conversion(*, doc_id: int, settings: Any) -> None:
    """在已持有单文档锁的前提下执行文档解析。"""

    from app.db.session import close_engine, get_session_factory, init_engine
    from app.modules.document.processing import convert_uploaded_document
    from app.modules.document.repository import DocumentRepository

    await init_engine(settings.database_url)
    mineru_client = _LazyMinerUClient(settings)
    try:
        await convert_uploaded_document(
            doc_id=doc_id,
            document_repository=DocumentRepository(get_session_factory()),
            storage=_LazyDocumentStorage(settings),
            mineru_client=mineru_client,
        )
    finally:
        await mineru_client.aclose()
        await close_engine()


class _LazyDocumentStorage:
    """只在 PDF 分支真正访问对象存储时创建 MinIO storage。"""

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._storage: Any | None = None

    def _get_storage(self) -> Any:
        if self._storage is None:
            from app.infrastructure.minio import get_minio_client
            from app.modules.document.storage import DocumentObjectStorage

            minio_client = get_minio_client()
            self._storage = DocumentObjectStorage(
                client=minio_client,
                bucket=self._settings.minio_bucket,
                public_base_url=self._settings.minio_public_base_url,
            )
        return self._storage

    async def upload_bytes(
        self,
        *,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> str:
        return await self._get_storage().upload_bytes(
            object_key=object_key,
            content=content,
            content_type=content_type,
        )

    async def download_bytes(self, *, object_key: str) -> bytes:
        return await self._get_storage().download_bytes(object_key=object_key)


class _LazyMinerUClient:
    """只在 PDF 分支真正请求 MinerU 时创建 HTTP client。"""

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            from app.infrastructure.mineru import create_mineru_client

            self._client = create_mineru_client(self._settings)
        return self._client

    async def request_zip(self, *, filename: str, content: bytes) -> bytes:
        return await self._get_client().request_zip(filename=filename, content=content)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
