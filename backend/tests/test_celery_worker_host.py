import importlib
import inspect
import sys


def test_celery_worker_exposes_app_with_document_task_include(monkeypatch):
    from app.infrastructure import celery_app

    calls = []
    missing = object()
    module_name = "app.workers.celery_worker"
    workers_package = importlib.import_module("app.workers")
    previous_module = sys.modules.get(module_name, missing)
    previous_parent_attr = getattr(workers_package, "celery_worker", missing)

    def fake_create_celery_app(*, include):
        calls.append(include)
        return "celery-app"

    monkeypatch.setattr(celery_app, "create_celery_app", fake_create_celery_app)
    sys.modules.pop(module_name, None)
    if hasattr(workers_package, "celery_worker"):
        delattr(workers_package, "celery_worker")

    try:
        celery_worker = importlib.import_module(module_name)

        assert celery_worker.celery_app == "celery-app"
        assert calls == [["app.modules.document.tasks.vector_storage_compensation"]]
    finally:
        if previous_module is missing:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module

        if previous_parent_attr is missing:
            if hasattr(workers_package, "celery_worker"):
                delattr(workers_package, "celery_worker")
        else:
            setattr(workers_package, "celery_worker", previous_parent_attr)


def test_celery_worker_parent_package_import_uses_real_app_after_fake_import():
    from app.workers import celery_worker

    assert celery_worker.celery_app.main == "ke_engine"


def test_celery_worker_host_owns_runtime_lifecycle_hooks():
    from app.workers import celery_worker

    source = inspect.getsource(celery_worker)

    assert "worker_process_init.connect" in source
    assert "worker_process_shutdown.connect" in source
    assert "start_celery_worker_runtime" in source
    assert "shutdown_celery_worker_runtime" in source
