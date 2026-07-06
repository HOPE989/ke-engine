from types import SimpleNamespace


def test_create_celery_app_uses_redis_json_and_utc(monkeypatch):
    from app.infrastructure import celery_app
    from app.modules.document.tasks.vector_storage_compensation import (
        DOCUMENT_VECTOR_STORAGE_COMPENSATION_INTERVAL_SECONDS,
        DOCUMENT_VECTOR_STORAGE_COMPENSATION_TASK_NAME,
    )

    monkeypatch.setattr(
        celery_app,
        "get_settings",
        lambda: SimpleNamespace(redis_url="redis://redis.example:6379/4"),
    )

    app = celery_app.create_celery_app(
        include=["app.modules.document.tasks.vector_storage_compensation"]
    )

    assert app.main == "ke_engine"
    assert app.conf.broker_url == "redis://redis.example:6379/4"
    assert app.conf.task_serializer == "json"
    assert list(app.conf.accept_content) == ["json"]
    assert app.conf.result_serializer == "json"
    assert app.conf.timezone == "UTC"
    assert app.conf.enable_utc is True
    assert app.conf.include == ["app.modules.document.tasks.vector_storage_compensation"]
    assert app.conf.beat_schedule == {
        "document-vector-storage-compensation": {
            "task": DOCUMENT_VECTOR_STORAGE_COMPENSATION_TASK_NAME,
            "schedule": DOCUMENT_VECTOR_STORAGE_COMPENSATION_INTERVAL_SECONDS,
        }
    }
