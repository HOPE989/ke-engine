"""Celery worker process entrypoint."""

from __future__ import annotations

from app.infrastructure.celery_app import create_celery_app


celery_app = create_celery_app(
    include=[
        "app.modules.document.tasks.vector_storage_compensation",
    ]
)
