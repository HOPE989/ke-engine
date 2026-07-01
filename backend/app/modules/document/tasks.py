"""文档转换 Celery 任务。"""

from __future__ import annotations

import asyncio

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
    """为 worker 单次任务创建运行时资源并执行解析。"""

    from app.db.session import close_engine, get_session_factory, init_engine
    from app.infrastructure.mineru import create_mineru_client
    from app.infrastructure.minio import ensure_minio_bucket, get_minio_client
    from app.infrastructure.redis_lock import create_redis_client, document_conversion_lock
    from app.modules.document.processing import convert_document_with_lock
    from app.modules.document.repository import DocumentRepository
    from app.modules.document.storage import DocumentObjectStorage

    settings = get_settings()
    redis_client = create_redis_client(settings.redis_url)
    mineru_client = create_mineru_client(settings)
    await init_engine(settings.database_url)
    try:
        minio_client = get_minio_client()
        await ensure_minio_bucket(minio_client, settings.minio_bucket)
        storage = DocumentObjectStorage(
            client=minio_client,
            bucket=settings.minio_bucket,
            public_base_url=settings.minio_public_base_url,
        )
        lock = document_conversion_lock(
            redis_client=redis_client,
            doc_id=doc_id,
            expire_seconds=settings.document_convert_lock_expire_seconds,
        )
        await convert_document_with_lock(
            doc_id=doc_id,
            document_repository=DocumentRepository(get_session_factory()),
            storage=storage,
            mineru_client=mineru_client,
            lock=lock,
        )
    finally:
        await mineru_client.aclose()
        redis_client.close()
        await close_engine()
