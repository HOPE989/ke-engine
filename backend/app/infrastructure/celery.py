"""Celery 应用实例。"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ke-engine",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    accept_content=["json"],
    result_serializer="json",
    task_serializer="json",
    timezone="UTC",
    imports=("app.modules.document.tasks",),
)
