# Document Vector Storage Compensation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Celery + Redis periodic compensation path that scans stale `CHUNKED` documents and reuses the existing document vector-storage runner.

**Architecture:** Celery Beat periodically publishes a document vector-storage compensation task to Redis, and a Celery Worker executes it outside the FastAPI and Kafka worker processes. The task scans stale `CHUNKED` document IDs through `DocumentRepository`, closes the scan session, then calls `run_document_vector_storage(doc_id)` for each candidate so existing Redis document locks, state idempotency, Elasticsearch cleanup, and Kafka offset boundaries remain unchanged.

**Tech Stack:** Python 3.11, FastAPI project layout, SQLAlchemy async, Redis, Celery `celery[redis]`, pytest, pytest-asyncio, uv.

---

## File Structure

- Modify: `backend/pyproject.toml`
  - Add `celery[redis]>=5.5.0,<6.0.0`.
- Modify: `backend/uv.lock`
  - Regenerate with `uv sync`.
- Modify: `backend/tests/test_document_config.py`
  - Assert Celery is available as a document background-task dependency.
- Modify: `backend/tests/test_document_persistence.py`
  - Add repository scan test for stale `CHUNKED` document IDs.
- Modify: `backend/app/modules/document/repository.py`
  - Add `list_stale_chunked_document_ids(older_than=timedelta)`.
- Create: `backend/tests/test_document_vector_storage_compensation_task.py`
  - Cover scan lifecycle, per-document runner calls, result counting, exception isolation, sync Celery wrapper, and Kafka-boundary safety.
- Create: `backend/app/modules/document/tasks/__init__.py`
  - Package marker for document Celery tasks.
- Create: `backend/app/modules/document/tasks/vector_storage_compensation.py`
  - Implement the periodic task and async compensation function.
- Create: `backend/tests/test_celery_app.py`
  - Cover Redis broker configuration, JSON serialization, UTC settings, and periodic schedule registration.
- Create: `backend/app/infrastructure/celery_app.py`
  - Create the process-local Celery app from project settings.
  - Register the document vector-storage compensation beat schedule.
- Create: `backend/tests/test_celery_worker_host.py`
  - Cover the global Celery worker entrypoint include list.
- Create: `backend/app/workers/celery_worker.py`
  - Expose `celery_app` for `celery -A`.
- Modify: `backend/tests/test_backend_makefile.py`
  - Assert local Celery worker and beat commands are documented.
- Modify: `Makefile`
  - Add `dev-celery-worker` and `dev-celery-beat` targets.

---

### Task 1: Celery Dependency

**Files:**
- Modify: `backend/tests/test_document_config.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`

- [ ] **Step 1: Write the failing dependency test**

In `backend/tests/test_document_config.py`, update `test_document_vector_storage_dependencies_are_available()` from:

```python
def test_document_vector_storage_dependencies_are_available():
    assert importlib.util.find_spec("langchain_elasticsearch") is not None
```

to:

```python
def test_document_vector_storage_dependencies_are_available():
    assert importlib.util.find_spec("langchain_elasticsearch") is not None
    assert importlib.util.find_spec("celery") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && uv run python -m pytest tests/test_document_config.py::test_document_vector_storage_dependencies_are_available -v
```

Expected: fail because `celery` is not available yet.

- [ ] **Step 3: Add Celery dependency**

In `backend/pyproject.toml`, add this dependency near the other runtime dependencies:

```toml
"celery[redis]>=5.5.0,<6.0.0",
```

Run:

```bash
cd backend && uv sync
```

Expected: `backend/uv.lock` is updated and `uv run python -c "import celery; print(celery.__version__)"` exits with code 0.

- [ ] **Step 4: Run focused dependency test**

Run:

```bash
cd backend && uv run python -m pytest tests/test_document_config.py::test_document_vector_storage_dependencies_are_available -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/tests/test_document_config.py
git commit -m "chore: add celery dependency for document compensation"
```

### Task 2: Stale CHUNKED Repository Scan

**Files:**
- Modify: `backend/tests/test_document_persistence.py`
- Modify: `backend/app/modules/document/repository.py`

- [ ] **Step 1: Write the failing repository scan test**

In `backend/tests/test_document_persistence.py`, add this import at the top:

```python
from datetime import timedelta
```

Add this test after `test_get_document_selects_by_doc_id()`:

```python
@pytest.mark.asyncio
async def test_list_stale_chunked_document_ids_filters_by_status_cutoff_and_orders():
    repository, _, _, _, _ = _document_modules()
    session_factory = FakeSessionFactory(scalars_result=[1001, 1002])
    document_repository = repository.DocumentRepository(session_factory)

    result = await document_repository.list_stale_chunked_document_ids(
        older_than=timedelta(minutes=5)
    )

    session = session_factory.sessions[0]
    statement = session.executed[0]
    sql = _compiled_sql(statement)
    assert result == [1001, 1002]
    assert "SELECT knowledge_document.doc_id" in sql
    assert "knowledge_document.status = 'CHUNKED'" in sql
    assert "knowledge_document.updated_at <" in sql
    assert "ORDER BY knowledge_document.updated_at ASC, knowledge_document.doc_id ASC" in sql
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && uv run python -m pytest tests/test_document_persistence.py::test_list_stale_chunked_document_ids_filters_by_status_cutoff_and_orders -v
```

Expected: fail with `AttributeError` because `DocumentRepository.list_stale_chunked_document_ids` does not exist.

- [ ] **Step 3: Implement the repository method**

In `backend/app/modules/document/repository.py`, add this import:

```python
from datetime import UTC, datetime, timedelta
```

Add this method inside `DocumentRepository`, after `get_document()`:

```python
    async def list_stale_chunked_document_ids(self, *, older_than: timedelta) -> list[int]:
        """Return stale CHUNKED document IDs ordered for deterministic compensation."""

        cutoff = datetime.now(UTC) - older_than
        async with self._session_factory() as session:
            result = await session.execute(
                select(KnowledgeDocument.doc_id)
                .where(
                    KnowledgeDocument.status == DocumentStatus.CHUNKED.value,
                    KnowledgeDocument.updated_at < cutoff,
                )
                .order_by(KnowledgeDocument.updated_at.asc(), KnowledgeDocument.doc_id.asc())
            )
            return list(result.scalars().all())
```

- [ ] **Step 4: Run focused repository tests**

Run:

```bash
cd backend && uv run python -m pytest tests/test_document_persistence.py::test_list_stale_chunked_document_ids_filters_by_status_cutoff_and_orders tests/test_document_persistence.py::test_list_pending_embeddable_segments_uses_fixed_first_page_ordering -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/document/repository.py backend/tests/test_document_persistence.py
git commit -m "feat: scan stale chunked documents"
```

### Task 3: Document Vector-Storage Compensation Task

**Files:**
- Create: `backend/tests/test_document_vector_storage_compensation_task.py`
- Create: `backend/app/modules/document/tasks/__init__.py`
- Create: `backend/app/modules/document/tasks/vector_storage_compensation.py`

- [ ] **Step 1: Write failing compensation task tests**

Create `backend/tests/test_document_vector_storage_compensation_task.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && uv run python -m pytest tests/test_document_vector_storage_compensation_task.py -v
```

Expected: fail because `app.modules.document.tasks.vector_storage_compensation` does not exist.

- [ ] **Step 3: Create the tasks package marker**

Create `backend/app/modules/document/tasks/__init__.py`:

```python
"""Document module Celery tasks."""
```

- [ ] **Step 4: Implement the compensation task**

Create `backend/app/modules/document/tasks/vector_storage_compensation.py`:

```python
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
```

- [ ] **Step 5: Run focused compensation tests**

Run:

```bash
cd backend && uv run python -m pytest tests/test_document_vector_storage_compensation_task.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/document/tasks backend/tests/test_document_vector_storage_compensation_task.py
git commit -m "feat: add document vector storage compensation task"
```

### Task 4: Celery App, Worker Entrypoint, and Local Commands

**Files:**
- Create: `backend/tests/test_celery_app.py`
- Create: `backend/tests/test_celery_worker_host.py`
- Modify: `backend/tests/test_backend_makefile.py`
- Create: `backend/app/infrastructure/celery_app.py`
- Create: `backend/app/workers/celery_worker.py`
- Modify: `Makefile`

- [ ] **Step 1: Write the failing Celery app test**

Create `backend/tests/test_celery_app.py`:

```python
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
```

- [ ] **Step 2: Write the failing Celery worker host test**

Create `backend/tests/test_celery_worker_host.py`:

```python
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
```

- [ ] **Step 3: Write the failing Makefile target test**

In `backend/tests/test_backend_makefile.py`, add this test:

```python
def test_root_makefile_exposes_celery_compensation_targets():
    makefile = Path(__file__).resolve().parents[2] / "Makefile"

    content = makefile.read_text(encoding="utf-8")

    assert "dev-celery-worker:" in content
    assert "dev-celery-beat:" in content
    assert "celery -A app.workers.celery_worker.celery_app worker -l INFO --pool=solo" in content
    assert "celery -A app.workers.celery_worker.celery_app beat -l INFO" in content
```

- [ ] **Step 4: Run tests to verify they fail**

Run:

```bash
cd backend && uv run python -m pytest tests/test_celery_app.py tests/test_celery_worker_host.py tests/test_backend_makefile.py::test_root_makefile_exposes_celery_compensation_targets -v
```

Expected: fail because `app.infrastructure.celery_app`, `app.workers.celery_worker`, and Makefile Celery targets do not exist yet.

- [ ] **Step 5: Create the Celery app module**

Create `backend/app/infrastructure/celery_app.py`:

```python
"""Celery application factory for process-level background tasks."""

from __future__ import annotations

from collections.abc import Iterable

from celery import Celery

from app.core.config import get_settings
from app.modules.document.tasks.vector_storage_compensation import (
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
```

- [ ] **Step 6: Implement the Celery worker entrypoint**

Create `backend/app/workers/celery_worker.py`:

```python
"""Celery worker process entrypoint."""

from __future__ import annotations

from app.infrastructure.celery_app import create_celery_app


celery_app = create_celery_app(
    include=[
        "app.modules.document.tasks.vector_storage_compensation",
    ]
)
```

- [ ] **Step 7: Add local Makefile targets**

In `Makefile`, update `.PHONY` from:

```makefile
.PHONY: help backend-sync dev dev-api dev-worker dev-infra dev-all-infra db-init kafka-topics-init kafka-topics-list test-backend
```

to:

```makefile
.PHONY: help backend-sync dev dev-api dev-worker dev-celery-worker dev-celery-beat dev-infra dev-all-infra db-init kafka-topics-init kafka-topics-list test-backend
```

Add these help lines under `help:`:

```makefile
	@echo "  make dev-celery-worker Start Celery worker for scheduled compensation tasks"
	@echo "  make dev-celery-beat  Start Celery beat scheduler"
```

Add these targets after `dev-worker:`:

```makefile
dev-celery-worker:
	cd $(BACKEND_DIR) && $(UV) run celery -A app.workers.celery_worker.celery_app worker -l INFO --pool=solo

dev-celery-beat:
	cd $(BACKEND_DIR) && $(UV) run celery -A app.workers.celery_worker.celery_app beat -l INFO
```

- [ ] **Step 8: Run focused Celery app, worker, and Makefile tests**

Run:

```bash
cd backend && uv run python -m pytest tests/test_celery_app.py tests/test_celery_worker_host.py tests/test_backend_makefile.py -v
```

Expected: pass.

- [ ] **Step 9: Commit**

```bash
git add backend/app/infrastructure/celery_app.py backend/app/workers/celery_worker.py backend/tests/test_celery_app.py backend/tests/test_celery_worker_host.py backend/tests/test_backend_makefile.py Makefile
git commit -m "feat: add celery compensation worker entrypoint"
```

### Task 5: Focused Integration Verification

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run document compensation tests**

Run:

```bash
cd backend && uv run python -m pytest tests/test_celery_app.py tests/test_celery_worker_host.py tests/test_document_vector_storage_compensation_task.py tests/test_document_persistence.py::test_list_stale_chunked_document_ids_filters_by_status_cutoff_and_orders tests/test_document_vector_storage_worker.py -v
```

Expected: pass. This proves the new compensation path exists, stale scan SQL is covered, the compensation task reuses `run_document_vector_storage`, and existing Kafka commit semantics remain covered.

- [ ] **Step 2: Run configuration and local command tests**

Run:

```bash
cd backend && uv run python -m pytest tests/test_document_config.py tests/test_backend_makefile.py -v
```

Expected: pass. This proves Celery is installed and local startup commands are documented.

- [ ] **Step 3: Import the Celery CLI target**

Run:

```bash
cd backend && uv run python -c "from app.workers.celery_worker import celery_app; print(celery_app.main)"
```

Expected:

```text
ke_engine
```

- [ ] **Step 4: Run the full backend test suite**

Run:

```bash
cd backend && uv run python -m pytest
```

Expected: all tests pass.

- [ ] **Step 5: Verify source boundaries**

Run:

```bash
rg -n "handle_document_vector_storage_message|store_document_vectors|\\.commit\\(" backend/app/modules/document/tasks backend/app/infrastructure/celery_app.py backend/app/workers/celery_worker.py
```

Expected: no matches. The compensation task must not call the Kafka handler, low-level vector store workflow, or Kafka commit APIs.

Run:

```bash
rg -n "run_document_vector_storage" backend/app/modules/document/tasks/vector_storage_compensation.py
```

Expected:

```text
backend/app/modules/document/tasks/vector_storage_compensation.py:<line>:from app.modules.document.workers.vector_storage import run_document_vector_storage
backend/app/modules/document/tasks/vector_storage_compensation.py:<line>:            stored = await run_document_vector_storage(doc_id=doc_id)
```

- [ ] **Step 6: Verify repository status**

Run:

```bash
git status --short
```

Expected: clean after the implementation commits.

---

## Self-Review

- Spec coverage:
  - Celery + Redis scheduler and worker runtime: Tasks 1 and 4.
  - Reuse `run_document_vector_storage(doc_id)`: Task 3.
  - Avoid Kafka commit and low-level `store_document_vectors()`: Task 3 test and Task 5 boundary grep.
  - Stale `CHUNKED` scan with five-minute threshold and stable ordering: Task 2 and Task 3 constants.
  - No global compensation lock and no doc-level scan limit: Task 3 implementation loops all scanned IDs and relies on existing per-document runner semantics.
  - Short scan DB session closed before per-document processing: Task 3 `_scan_stale_chunked_document_ids()` test.
  - Celery worker entrypoint and local commands: Task 4.
  - Focused tests for repository scan, task counting, false results, exceptions, Celery app schedule, and Kafka boundary safety: Tasks 1 through 5.
- Placeholder scan:
  - No unresolved placeholders or vague implementation-only steps remain.
  - Each code-changing step includes exact file paths and concrete snippets.
- Type consistency:
  - `list_stale_chunked_document_ids(older_than: timedelta) -> list[int]` is used by `_scan_stale_chunked_document_ids()`.
  - `compensate_stale_chunked_document_vectors() -> dict[str, int]` is returned by the Celery sync wrapper.
  - The Celery beat schedule task name matches `@shared_task(name=DOCUMENT_VECTOR_STORAGE_COMPENSATION_TASK_NAME)`.
