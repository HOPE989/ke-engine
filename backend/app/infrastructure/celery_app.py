"""Celery application factory for process-level background tasks."""

from __future__ import annotations

from collections.abc import Iterable

from celery import Celery

from app.core.config import get_settings
from app.domains.document.tasks.vector_storage_compensation import (
    DOCUMENT_VECTOR_STORAGE_COMPENSATION_INTERVAL_SECONDS,
    DOCUMENT_VECTOR_STORAGE_COMPENSATION_TASK_NAME,
)


def create_celery_app(*, include: Iterable[str] | None = None) -> Celery:
    """Create a Celery app backed by the existing Redis deployment."""

    settings = get_settings()
    app = Celery(
        "ke_engine",
        broker=settings.redis_url,
        include=list(include or []),
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        beat_schedule={
            "document-vector-storage-compensation": {
                "task": DOCUMENT_VECTOR_STORAGE_COMPENSATION_TASK_NAME,
                "schedule": DOCUMENT_VECTOR_STORAGE_COMPENSATION_INTERVAL_SECONDS,
            }
        },
    )
    return app
