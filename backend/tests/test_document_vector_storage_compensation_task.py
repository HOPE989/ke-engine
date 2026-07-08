import inspect
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_scan_stale_chunked_document_ids_uses_celery_runtime_repository(monkeypatch):
    from app.domains.document.tasks import vector_storage_compensation as task

    calls = []

    class FakeDocumentRepository:
        async def list_stale_chunked_document_ids(self, *, older_than):
            calls.append(("list_stale", older_than))
            return [42, 43]

    async def fail_db_lifecycle(*args, **kwargs):
        raise AssertionError("Celery compensation scan must use runtime-owned DB resources")

    monkeypatch.setattr("app.infrastructure.db.session.init_engine", fail_db_lifecycle)
    monkeypatch.setattr("app.infrastructure.db.session.close_engine", fail_db_lifecycle)

    result = await task._scan_stale_chunked_document_ids(
        runtime=SimpleNamespace(
            compensation=SimpleNamespace(repository=FakeDocumentRepository())
        )
    )

    assert result == [42, 43]
    assert calls == [("list_stale", task.STALE_CHUNKED_THRESHOLD)]


@pytest.mark.asyncio
async def test_compensation_runs_vector_storage_for_each_stale_document(monkeypatch):
    from app.domains.document.tasks import vector_storage_compensation as task

    calls = []
    runtime = object()

    async def fake_scan_stale_chunked_document_ids(*, runtime):
        calls.append(("scan", runtime))
        return [42, 43, 44]

    async def fake_run_document_vector_storage_with_runtime(*, doc_id, runtime):
        calls.append(("run", doc_id, runtime))
        return doc_id != 43

    monkeypatch.setattr(
        task,
            "_scan_stale_chunked_document_ids",
            fake_scan_stale_chunked_document_ids,
    )
    monkeypatch.setattr(
        task,
        "run_document_vector_storage_with_runtime",
        fake_run_document_vector_storage_with_runtime,
    )

    summary = await task.compensate_stale_chunked_document_vectors(runtime=runtime)

    assert calls == [
        ("scan", runtime),
        ("run", 42, runtime),
        ("run", 43, runtime),
        ("run", 44, runtime),
    ]
    assert summary == {"total": 3, "succeeded": 2, "failed": 1}


@pytest.mark.asyncio
async def test_compensation_counts_unexpected_document_exception_and_continues(monkeypatch):
    from app.domains.document.tasks import vector_storage_compensation as task

    calls = []
    runtime = object()

    async def fake_scan_stale_chunked_document_ids(*, runtime):
        return [42, 43]

    async def fake_run_document_vector_storage_with_runtime(*, doc_id, runtime):
        calls.append(doc_id)
        if doc_id == 42:
            raise RuntimeError("openai unavailable")
        return True

    monkeypatch.setattr(
        task,
            "_scan_stale_chunked_document_ids",
            fake_scan_stale_chunked_document_ids,
    )
    monkeypatch.setattr(
        task,
        "run_document_vector_storage_with_runtime",
        fake_run_document_vector_storage_with_runtime,
    )

    summary = await task.compensate_stale_chunked_document_vectors(runtime=runtime)

    assert calls == [42, 43]
    assert summary == {"total": 2, "succeeded": 1, "failed": 1}


def test_celery_task_wrapper_submits_async_compensation_to_runtime_loop(monkeypatch):
    from app.domains.document.tasks import vector_storage_compensation as task
    from app.entrypoints import celery_worker

    calls = []
    runtime = object()

    async def fake_compensate_stale_chunked_document_vectors(*, runtime):
        calls.append(("workflow", runtime))
        return {"total": 0, "succeeded": 0, "failed": 0}

    def fake_submit_celery_runtime_coroutine(coroutine):
        calls.append(("submit", inspect.iscoroutine(coroutine)))
        coroutine.close()
        return {"total": 0, "succeeded": 0, "failed": 0}

    monkeypatch.setattr(
        task,
        "compensate_stale_chunked_document_vectors",
        fake_compensate_stale_chunked_document_vectors,
    )
    monkeypatch.setattr(celery_worker, "get_celery_worker_runtime", lambda: runtime)
    monkeypatch.setattr(
        celery_worker,
        "submit_celery_runtime_coroutine",
        fake_submit_celery_runtime_coroutine,
    )
    result = task.compensate_stale_chunked_document_vectors_task.run()

    assert result == {"total": 0, "succeeded": 0, "failed": 0}
    assert calls == [("submit", True)]


def test_celery_task_wrapper_does_not_call_asyncio_run():
    from app.domains.document.tasks import vector_storage_compensation as task

    source = inspect.getsource(task.compensate_stale_chunked_document_vectors_task)

    assert "asyncio.run(" not in source


def test_shutdown_celery_worker_runtime_releases_resources_and_closes_loop(monkeypatch):
    import asyncio as real_asyncio

    from app.entrypoints import celery_worker

    calls = []

    class FakeStack:
        async def __aexit__(self, exc_type, exc, tb):
            calls.append(("stack_exit", None))

    class FakeLoop:
        def __init__(self):
            self.closed = False

        def call_soon_threadsafe(self, callback):
            calls.append(("call_soon_threadsafe", callback.__name__))
            callback()

        def stop(self):
            calls.append(("loop_stop", None))

        def close(self):
            calls.append(("loop_close", None))
            self.closed = True

        def is_closed(self):
            return self.closed

    class FakeThread:
        def join(self, timeout=None):
            calls.append(("thread_join", timeout))

    class FakeFuture:
        def result(self):
            calls.append(("future_result", None))

    def fake_run_coroutine_threadsafe(coroutine, loop):
        calls.append(("submit_cleanup", loop))
        real_asyncio.run(coroutine)
        return FakeFuture()

    fake_loop = FakeLoop()
    celery_worker._celery_worker_runtime = object()
    celery_worker._celery_worker_runtime_stack = FakeStack()
    celery_worker._celery_worker_loop = fake_loop
    celery_worker._celery_worker_loop_thread = FakeThread()
    monkeypatch.setattr(
        celery_worker.asyncio,
        "run_coroutine_threadsafe",
        fake_run_coroutine_threadsafe,
    )

    celery_worker.shutdown_celery_worker_runtime()

    assert calls == [
        ("submit_cleanup", fake_loop),
        ("stack_exit", None),
        ("future_result", None),
        ("call_soon_threadsafe", "stop"),
        ("loop_stop", None),
        ("thread_join", 5),
        ("loop_close", None),
    ]
    assert celery_worker._celery_worker_runtime is None
    assert celery_worker._celery_worker_runtime_stack is None
    assert celery_worker._celery_worker_loop is None
    assert celery_worker._celery_worker_loop_thread is None


def test_compensation_task_uses_runner_without_kafka_commit_or_low_level_store():
    from app.domains.document.tasks import vector_storage_compensation as task

    source = inspect.getsource(task)

    assert "run_document_vector_storage_with_runtime(" in source
    assert "handle_document_vector_storage_message" not in source
    assert "store_document_vectors(" not in source
    assert ".commit(" not in source


def test_compensation_module_does_not_own_worker_process_lifecycle_hooks():
    from app.domains.document.tasks import vector_storage_compensation as task

    source = inspect.getsource(task)

    assert "worker_process_init.connect" not in source
    assert "worker_process_shutdown.connect" not in source
    assert "start_celery_worker_runtime" not in source
    assert "shutdown_celery_worker_runtime" not in source
