import inspect
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_scan_stale_chunked_document_ids_initializes_and_closes_engine(monkeypatch):
    from app.modules.document.tasks import vector_storage_compensation as task

    calls = []

    async def fake_init_engine(database_url):
        calls.append(("init_engine", database_url))

    async def fake_close_engine():
        calls.append(("close_engine", None))

    def fake_get_session_factory():
        calls.append(("get_session_factory", None))
        return "session-factory"

    class FakeDocumentRepository:
        def __init__(self, session_factory):
            calls.append(("create_repository", session_factory))

        async def list_stale_chunked_document_ids(self, *, older_than):
            calls.append(("list_stale", older_than))
            return [42, 43]

    monkeypatch.setattr(task.db_session, "init_engine", fake_init_engine)
    monkeypatch.setattr(task.db_session, "close_engine", fake_close_engine)
    monkeypatch.setattr(task.db_session, "get_session_factory", fake_get_session_factory)
    monkeypatch.setattr(
        task.document_repository_module,
        "DocumentRepository",
        FakeDocumentRepository,
    )

    result = await task._scan_stale_chunked_document_ids(
        settings=SimpleNamespace(database_url="postgresql+asyncpg://db/app")
    )

    assert result == [42, 43]
    assert calls == [
        ("init_engine", "postgresql+asyncpg://db/app"),
        ("get_session_factory", None),
        ("create_repository", "session-factory"),
        ("list_stale", task.STALE_CHUNKED_THRESHOLD),
        ("close_engine", None),
    ]


@pytest.mark.asyncio
async def test_compensation_runs_vector_storage_for_each_stale_document(monkeypatch):
    from app.modules.document.tasks import vector_storage_compensation as task

    calls = []

    monkeypatch.setattr(task, "get_settings", lambda: SimpleNamespace(database_url="db-url"))

    async def fake_scan_stale_chunked_document_ids(*, settings):
        calls.append(("scan", settings.database_url))
        return [42, 43, 44]

    async def fake_run_document_vector_storage(doc_id):
        calls.append(("run", doc_id))
        return doc_id != 43

    monkeypatch.setattr(
        task,
        "_scan_stale_chunked_document_ids",
        fake_scan_stale_chunked_document_ids,
    )
    monkeypatch.setattr(task, "run_document_vector_storage", fake_run_document_vector_storage)

    summary = await task.compensate_stale_chunked_document_vectors()

    assert calls == [
        ("scan", "db-url"),
        ("run", 42),
        ("run", 43),
        ("run", 44),
    ]
    assert summary == {"total": 3, "succeeded": 2, "failed": 1}


@pytest.mark.asyncio
async def test_compensation_counts_unexpected_document_exception_and_continues(monkeypatch):
    from app.modules.document.tasks import vector_storage_compensation as task

    calls = []

    monkeypatch.setattr(task, "get_settings", lambda: SimpleNamespace(database_url="db-url"))

    async def fake_scan_stale_chunked_document_ids(*, settings):
        return [42, 43]

    async def fake_run_document_vector_storage(doc_id):
        calls.append(doc_id)
        if doc_id == 42:
            raise RuntimeError("openai unavailable")
        return True

    monkeypatch.setattr(
        task,
        "_scan_stale_chunked_document_ids",
        fake_scan_stale_chunked_document_ids,
    )
    monkeypatch.setattr(task, "run_document_vector_storage", fake_run_document_vector_storage)

    summary = await task.compensate_stale_chunked_document_vectors()

    assert calls == [42, 43]
    assert summary == {"total": 2, "succeeded": 1, "failed": 1}


def test_celery_task_wrapper_runs_async_compensation(monkeypatch):
    from app.modules.document.tasks import vector_storage_compensation as task

    async def fake_compensate_stale_chunked_document_vectors():
        return {"total": 0, "succeeded": 0, "failed": 0}

    monkeypatch.setattr(
        task,
        "compensate_stale_chunked_document_vectors",
        fake_compensate_stale_chunked_document_vectors,
    )

    result = task.compensate_stale_chunked_document_vectors_task.run()

    assert result == {"total": 0, "succeeded": 0, "failed": 0}


def test_compensation_task_uses_runner_without_kafka_commit_or_low_level_store():
    from app.modules.document.tasks import vector_storage_compensation as task

    source = inspect.getsource(task)

    assert "run_document_vector_storage(" in source
    assert "handle_document_vector_storage_message" not in source
    assert "store_document_vectors(" not in source
    assert ".commit(" not in source
