"""Document conversion Kafka worker."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.infrastructure.kafka import create_kafka_consumer
from app.modules.document.events import (
    DOCUMENT_CONVERT_GROUP_ID,
    DOCUMENT_CONVERT_REQUESTED_TOPIC,
    DocumentConvertRequested,
)

logger = logging.getLogger(__name__)


async def run_document_conversion_consumer() -> None:
    """Run the long-lived document conversion Kafka consumer loop."""

    settings = get_settings()
    consumer = create_kafka_consumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=DOCUMENT_CONVERT_GROUP_ID,
    )
    await consumer.subscribe([DOCUMENT_CONVERT_REQUESTED_TOPIC])
    try:
        while True:
            message = await consumer.poll(timeout=1.0)
            if message is None:
                continue
            error = message.error()
            if error is not None:
                logger.warning("kafka consumer error: %s", error)
                continue
            await handle_document_conversion_message(message=message, consumer=consumer)
    finally:
        await consumer.close()


async def handle_document_conversion_message(*, message: Any, consumer: Any) -> None:
    """Handle and commit one document conversion Kafka message."""

    event = DocumentConvertRequested.from_json(message.value())
    await run_document_conversion(doc_id=event.doc_id_int())
    await consumer.commit(message=message)


async def run_document_conversion(doc_id: int) -> None:
    """Create per-message resources and execute document conversion."""

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
            await run_locked_document_conversion(doc_id=doc_id, settings=settings)
        finally:
            lock.release()
    finally:
        redis_client.close()


async def run_locked_document_conversion(*, doc_id: int, settings: Any) -> None:
    """Execute document conversion while holding the per-document lock."""

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
    """Create MinIO storage only when a PDF path needs object storage."""

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
    """Create MinerU HTTP client only when a PDF path needs conversion."""

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
