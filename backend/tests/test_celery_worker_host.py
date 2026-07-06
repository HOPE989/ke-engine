import importlib
import sys


def test_celery_worker_exposes_app_with_document_task_include(monkeypatch):
    from app.infrastructure import celery_app

    calls = []

    def fake_create_celery_app(*, include):
        calls.append(include)
        return "celery-app"

    monkeypatch.setattr(celery_app, "create_celery_app", fake_create_celery_app)
    module_name = "app.workers.celery_worker"
    sys.modules.pop(module_name, None)

    try:
        celery_worker = importlib.import_module(module_name)

        assert celery_worker.celery_app == "celery-app"
        assert calls == [["app.modules.document.tasks.vector_storage_compensation"]]
    finally:
        sys.modules.pop(module_name, None)


def test_celery_worker_import_uses_real_app_after_fake_import():
    celery_worker = importlib.import_module("app.workers.celery_worker")

    assert celery_worker.celery_app.main == "ke_engine"
