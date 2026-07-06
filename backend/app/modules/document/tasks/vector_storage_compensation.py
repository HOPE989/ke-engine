"""Celery compensation task for stale document vector storage."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from celery import shared_task

from app.core.config import get_settings
from app.db import session as db_session
from app.modules.document import repository as document_repository_module
from app.modules.document.workers.vector_storage import run_document_vector_storage

logger = logging.getLogger(__name__)

DOCUMENT_VECTOR_STORAGE_COMPENSATION_TASK_NAME = (
    "document.vector_storage.compensate_stale_chunked"
)
DOCUMENT_VECTOR_STORAGE_COMPENSATION_INTERVAL_SECONDS = 300.0
STALE_CHUNKED_THRESHOLD = timedelta(minutes=5)


@shared_task(name=DOCUMENT_VECTOR_STORAGE_COMPENSATION_TASK_NAME)
def compensate_stale_chunked_document_vectors_task() -> dict[str, int]:
    """Celery sync wrapper for the async compensation workflow."""

    return asyncio.run(compensate_stale_chunked_document_vectors())


async def compensate_stale_chunked_document_vectors() -> dict[str, int]:
    """Scan stale CHUNKED documents and reuse the vector-storage runner."""

    settings = get_settings()
    doc_ids = await _scan_stale_chunked_document_ids(settings=settings)
    summary = {"total": len(doc_ids), "succeeded": 0, "failed": 0}

    for doc_id in doc_ids:
        try:
            stored = await run_document_vector_storage(doc_id=doc_id)
        except Exception:
            logger.exception(
                "document vector-storage compensation failed unexpectedly",
                extra={"doc_id": doc_id},
            )
            summary["failed"] += 1
            continue

        if stored:
            summary["succeeded"] += 1
        else:
            logger.info(
                "document vector-storage compensation left document retryable",
                extra={"doc_id": doc_id},
            )
            summary["failed"] += 1

    logger.info("document vector-storage compensation finished", extra=summary)
    return summary


async def _scan_stale_chunked_document_ids(*, settings: Any) -> list[int]:
    """Open a short DB runtime only for scanning compensation candidates."""

    await db_session.init_engine(settings.database_url)
    try:
        repository = document_repository_module.DocumentRepository(
            db_session.get_session_factory()
        )
        return await repository.list_stale_chunked_document_ids(
            older_than=STALE_CHUNKED_THRESHOLD
        )
    finally:
        await db_session.close_engine()
