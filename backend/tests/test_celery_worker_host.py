import importlib
import sys


def test_celery_worker_exposes_app_with_document_task_include(monkeypatch):
    from app.infrastructure import celery_app

    calls = []

    def fake_create_celery_app(*, include):
        calls.append(include)
        return "celery-app"

    monkeypatch.setattr(celery_app, "create_celery_app", fake_create_celery_app)
    sys.modules.pop("app.workers.celery_worker", None)

    celery_worker = importlib.import_module("app.workers.celery_worker")

    assert celery_worker.celery_app == "celery-app"
    assert calls == [["app.modules.document.tasks.vector_storage_compensation"]]
