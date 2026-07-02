# Kafka Document Workers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Celery document conversion path with native Kafka dispatch and async Kafka worker runners.

**Architecture:** FastAPI upload keeps the durable `UPLOADED` write before dispatch, then sends a `document.convert.requested` Kafka event. A thin global worker host starts module-local document consumer runners; the document conversion runner consumes Kafka, uses the existing Redis document lock, calls `convert_uploaded_document()`, and commits offsets only after successful handling.

**Tech Stack:** FastAPI, asyncio, SQLAlchemy async, Redis lock, MinIO adapter, `confluent-kafka>=2.15.0,<3.0.0`, pytest, pytest-asyncio.

---

## File Structure

- Modify: `backend/pyproject.toml`
  - Remove `celery[redis]`.
  - Add `confluent-kafka>=2.15.0,<3.0.0`.
- Modify: `backend/uv.lock`
  - Regenerate with `uv sync`.
- Modify: `backend/app/core/config.py`
  - Remove Celery settings.
  - Add Kafka bootstrap settings.
- Modify: `backend/.env.example`
  - Remove Celery env names.
  - Add Kafka env names.
- Modify: `docker-compose.yml`
  - Add self-hosted Kafka for local development.
  - Include Kafka in lightweight infra.
- Modify: `Makefile`
  - Remove Celery worker variables.
  - Start `python -m app.workers.kafka_worker`.
- Create: `backend/app/infrastructure/kafka.py`
  - Lazy import and construct `AIOProducer` / `AIOConsumer`.
- Create: `backend/app/modules/document/events.py`
  - Define document conversion topic constants plus `DocumentConvertRequested` payload serialization and parsing.
- Create: `backend/app/modules/document/dispatcher.py`
  - Define `KafkaDocumentConversionDispatcher`.
- Create: `backend/app/modules/document/workers/__init__.py`
  - Package marker.
- Create: `backend/app/modules/document/workers/conversion.py`
  - Kafka consumer runner and document conversion execution.
- Create: `backend/app/workers/__init__.py`
  - Package marker.
- Create: `backend/app/workers/kafka_worker.py`
  - Global worker host entrypoint.
- Modify: `backend/app/api/deps.py`
  - Use `KafkaDocumentConversionDispatcher`.
- Delete: `backend/app/infrastructure/celery.py`
  - Celery app is removed.
- Delete: `backend/app/modules/document/tasks.py`
  - Celery task entrypoint is removed after moving reusable worker code.
- Modify tests:
  - Replace Celery assertions with Kafka assertions.
  - Add event, dispatcher, worker runner, and worker host tests.

---

### Task 1: Kafka Configuration, Dependency, and Local Runtime Wiring

**Files:**
- Modify: `backend/tests/test_document_config.py`
- Modify: `backend/tests/test_backend_makefile.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Modify: `Makefile`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Write failing configuration and Makefile tests**

Update `backend/tests/test_document_config.py` so `DOCUMENT_ENV_LINES` contains Kafka names instead of Celery names:

```python
DOCUMENT_ENV_LINES = [
    "DATABASE_URL=postgresql+asyncpg://user:pass@db.example:5432/app",
    "MAX_UPLOAD_SIZE_MB=25",
    "MINIO_ENDPOINT=minio.example:9000",
    "MINIO_ACCESS_KEY=minio-access",
    "MINIO_SECRET_KEY=minio-secret",
    "MINIO_BUCKET=documents",
    "MINIO_PUBLIC_BASE_URL=https://files.example.com",
    "MINIO_SECURE=true",
    "MINERU_BASE_URL=https://mineru.example.com",
    "MINERU_PROVIDER=official",
    "MINERU_API_KEY=mineru-key",
    "MINERU_MODEL_VERSION=vlm",
    "MINERU_POLL_INTERVAL_SECONDS=2",
    "MINERU_POLL_TIMEOUT_SECONDS=120",
    "MINERU_TIMEOUT_SECONDS=45",
    "REDIS_URL=redis://redis.example:6379/3",
    "KAFKA_BOOTSTRAP_SERVERS=kafka.example:9092",
    "DOCUMENT_CONVERT_LOCK_EXPIRE_SECONDS=180",
    "SNOWFLAKE_WORKER_ID=7",
    "OPENAI_API_KEY=openai-key",
    "OPENAI_BASE_URL=https://openai.example.com/v1",
    "OPENAI_MODEL=test-model",
]
```

Replace Celery assertions with:

```python
assert settings.kafka_bootstrap_servers == "kafka.example:9092"
```

Update the `.env.example` names list to include:

```python
"KAFKA_BOOTSTRAP_SERVERS",
```

and remove:

```python
"CELERY_BROKER_URL",
"CELERY_RESULT_BACKEND",
```

Update `test_document_upload_dependencies_are_available()` to assert:

```python
for module_name in ["alembic", "confluent_kafka", "minio", "magika", "multipart", "redis", "redis_lock"]:
    assert importlib.util.find_spec(module_name) is not None
```

Update `test_settings_document_startup_and_request_time_boundaries()` to include Kafka settings and remove Celery settings:

```python
assert config.STARTUP_ONLY_SETTINGS == {
    "database_url",
    "minio_endpoint",
    "minio_access_key",
    "minio_secret_key",
    "minio_bucket",
    "minio_public_base_url",
    "minio_secure",
    "mineru_base_url",
    "mineru_provider",
    "mineru_api_key",
    "mineru_model_version",
    "mineru_poll_interval_seconds",
    "mineru_poll_timeout_seconds",
    "mineru_timeout_seconds",
    "redis_url",
    "kafka_bootstrap_servers",
    "document_convert_lock_expire_seconds",
    "snowflake_worker_id",
}
```

Update `backend/tests/test_backend_makefile.py`:

```python
assert "$(UV) run python -m app.workers.kafka_worker" in content
assert "CELERY_POOL" not in content
assert "celery -A" not in content
assert "docker compose up -d postgres redis minio kafka" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && uv run python -m pytest tests/test_document_config.py tests/test_backend_makefile.py -v
```

Expected: fail because Kafka bootstrap settings, dependency, env names, and Makefile command do not exist yet.

- [ ] **Step 3: Implement configuration and local runtime changes**

In `backend/pyproject.toml`, replace:

```toml
"celery[redis]>=5.5.0",
```

with:

```toml
"confluent-kafka>=2.15.0,<3.0.0",
```

In `backend/app/core/config.py`, remove `celery_broker_url` and `celery_result_backend`, then add:

```python
kafka_bootstrap_servers: str = Field(
    default="localhost:9092",
    validation_alias="KAFKA_BOOTSTRAP_SERVERS",
    description="startup-only: Kafka clients are configured during process startup.",
)
```

Update `STARTUP_ONLY_SETTINGS` to match the test.

In `backend/.env.example`, replace the Celery lines with:

```text
KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:9092
```

In `Makefile`, remove `CELERY_APP`, `CELERY_LOG_LEVEL`, and `CELERY_POOL`, then set:

```makefile
dev-infra:
	docker compose up -d postgres redis minio kafka

dev-worker:
	cd $(BACKEND_DIR) && $(UV) run python -m app.workers.kafka_worker
```

In `docker-compose.yml`, add a local Kafka service:

```yaml
  kafka:
    image: apache/kafka:3.9.0
    container_name: ke-engine-kafka
    ports:
      - "9092:9092"
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://127.0.0.1:9092
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1
      KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS: 0
    volumes:
      - kafka-data:/var/lib/kafka/data
```

Add `kafka-data:` to `volumes`.

- [ ] **Step 4: Sync dependencies and verify tests pass**

Run:

```bash
cd backend && uv sync
cd backend && uv run python -m pytest tests/test_document_config.py tests/test_backend_makefile.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/core/config.py backend/.env.example Makefile docker-compose.yml backend/tests/test_document_config.py backend/tests/test_backend_makefile.py
git commit -m "chore: configure kafka worker runtime"
```

### Task 2: Kafka Event Schema and Client Factories

**Files:**
- Create: `backend/tests/test_document_kafka_events.py`
- Create: `backend/tests/test_kafka_infrastructure.py`
- Create: `backend/app/modules/document/events.py`
- Create: `backend/app/infrastructure/kafka.py`

- [ ] **Step 1: Write failing event and infrastructure tests**

Create `backend/tests/test_document_kafka_events.py`:

```python
import json

import pytest


def test_document_convert_requested_serializes_doc_id_as_string():
    from app.modules.document.events import (
        DOCUMENT_CONVERT_REQUESTED_TOPIC,
        DocumentConvertRequested,
    )

    event = DocumentConvertRequested.create(doc_id=42)

    payload = json.loads(event.to_json())

    assert payload["event_type"] == "document.convert.requested"
    assert payload["doc_id"] == "42"
    assert payload["event_id"]
    assert payload["occurred_at"].endswith("Z")
    assert DOCUMENT_CONVERT_REQUESTED_TOPIC == "document.convert.requested"


def test_document_convert_requested_rejects_wrong_event_type():
    from app.modules.document.events import DocumentConvertRequested

    with pytest.raises(ValueError, match="unsupported event_type"):
        DocumentConvertRequested.from_json(
            json.dumps(
                {
                    "event_id": "event-1",
                    "event_type": "wrong.type",
                    "doc_id": "42",
                    "occurred_at": "2026-07-02T00:00:00Z",
                }
            )
        )
```

Create `backend/tests/test_kafka_infrastructure.py`:

```python
def test_create_kafka_producer_uses_bootstrap_servers(monkeypatch):
    from app.infrastructure import kafka

    created_configs = []

    class FakeProducer:
        def __init__(self, config):
            created_configs.append(config)

    monkeypatch.setattr(kafka, "AIOProducer", FakeProducer)

    producer = kafka.create_kafka_producer("kafka.example:9092")

    assert isinstance(producer, FakeProducer)
    assert created_configs == [{"bootstrap.servers": "kafka.example:9092"}]


def test_create_kafka_consumer_disables_auto_commit(monkeypatch):
    from app.infrastructure import kafka

    created_configs = []

    class FakeConsumer:
        def __init__(self, config):
            created_configs.append(config)

    monkeypatch.setattr(kafka, "AIOConsumer", FakeConsumer)

    consumer = kafka.create_kafka_consumer(
        bootstrap_servers="kafka.example:9092",
        group_id="group-a",
    )

    assert isinstance(consumer, FakeConsumer)
    assert created_configs == [
        {
            "bootstrap.servers": "kafka.example:9092",
            "group.id": "group-a",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": "false",
        }
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && uv run python -m pytest tests/test_document_kafka_events.py tests/test_kafka_infrastructure.py -v
```

Expected: fail because modules do not exist.

- [ ] **Step 3: Implement event schema and client factories**

Create `backend/app/modules/document/events.py`:

```python
"""Kafka event payloads owned by the document module."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import uuid4


DOCUMENT_CONVERT_REQUESTED = "document.convert.requested"
DOCUMENT_CONVERT_REQUESTED_TOPIC = DOCUMENT_CONVERT_REQUESTED
DOCUMENT_CONVERT_GROUP_ID = "ke-engine-document-converter"


@dataclass(frozen=True, slots=True)
class DocumentConvertRequested:
    """Event requesting conversion for one uploaded document."""

    event_id: str
    event_type: str
    doc_id: str
    occurred_at: str

    @classmethod
    def create(cls, *, doc_id: int) -> "DocumentConvertRequested":
        return cls(
            event_id=str(uuid4()),
            event_type=DOCUMENT_CONVERT_REQUESTED,
            doc_id=str(doc_id),
            occurred_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> "DocumentConvertRequested":
        data = json.loads(payload)
        event = cls(
            event_id=str(data["event_id"]),
            event_type=str(data["event_type"]),
            doc_id=str(data["doc_id"]),
            occurred_at=str(data["occurred_at"]),
        )
        if event.event_type != DOCUMENT_CONVERT_REQUESTED:
            raise ValueError(f"unsupported event_type: {event.event_type}")
        int(event.doc_id)
        return event

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    def doc_id_int(self) -> int:
        return int(self.doc_id)
```

Create `backend/app/infrastructure/kafka.py`:

```python
"""Kafka client factories."""

from confluent_kafka.aio import AIOConsumer, AIOProducer


def create_kafka_producer(bootstrap_servers: str) -> AIOProducer:
    """Create an AsyncIO Kafka producer."""

    return AIOProducer({"bootstrap.servers": bootstrap_servers})


def create_kafka_consumer(*, bootstrap_servers: str, group_id: str) -> AIOConsumer:
    """Create an AsyncIO Kafka consumer with manual commits."""

    return AIOConsumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": "false",
        }
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend && uv run python -m pytest tests/test_document_kafka_events.py tests/test_kafka_infrastructure.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/document/events.py backend/app/infrastructure/kafka.py backend/tests/test_document_kafka_events.py backend/tests/test_kafka_infrastructure.py
git commit -m "feat: add document kafka event primitives"
```

### Task 3: Kafka Dispatcher and API Runtime Integration

**Files:**
- Modify: `backend/tests/test_document_async_infrastructure.py`
- Modify: `backend/tests/test_document_resource_ownership.py`
- Create: `backend/app/modules/document/dispatcher.py`
- Modify: `backend/app/api/deps.py`
- Modify: `backend/app/modules/document/workflow.py`

- [ ] **Step 1: Write failing dispatcher and runtime tests**

Replace the Celery dispatcher test in `backend/tests/test_document_async_infrastructure.py` with:

```python
@pytest.mark.asyncio
async def test_conversion_dispatcher_produces_kafka_event(monkeypatch):
    from app.modules.document import dispatcher

    calls = []

    class FakeDelivery:
        async def wait(self):
            calls.append(("delivery_wait", None))

    class FakeProducer:
        async def produce(self, *, topic, key, value):
            calls.append(("produce", topic, key, value))
            return FakeDelivery()

    await dispatcher.KafkaDocumentConversionDispatcher(FakeProducer()).dispatch(42)

    assert calls[0][0] == "produce"
    assert calls[0][1] == "document.convert.requested"
    assert calls[0][2] == b"42"
    assert b'"event_type":"document.convert.requested"' in calls[0][3]
    assert calls[1] == ("delivery_wait", None)
```

Update `backend/tests/test_document_resource_ownership.py`:

```python
def _document_settings():
    return SimpleNamespace(
        minio_endpoint="minio.example:9000",
        minio_access_key="access-key",
        minio_secret_key="secret-key",
        minio_secure=True,
        redis_url="redis://redis.example:6379/0",
        kafka_bootstrap_servers="kafka.example:9092",
        document_convert_lock_expire_seconds=120,
        snowflake_worker_id=7,
        mineru_provider="local",
        mineru_base_url="https://mineru.example.com",
        mineru_api_key=None,
        mineru_model_version="vlm",
        mineru_poll_interval_seconds=2,
        mineru_poll_timeout_seconds=300,
        mineru_timeout_seconds=30,
    )
```

Replace runtime source assertion:

```python
assert "KafkaDocumentConversionDispatcher(" in source
assert "create_kafka_producer(" in source
assert "CeleryDocumentConversionDispatcher(" not in source
```

Replace fake dispatcher patch in `test_document_runtime_ensures_storage_bucket_before_serving()`:

```python
class FakeKafkaDocumentConversionDispatcher:
    def __init__(self, producer):
        calls.append(("create_dispatcher", producer))

monkeypatch.setattr("app.infrastructure.kafka.create_kafka_producer", lambda bootstrap_servers: "producer")
monkeypatch.setattr(
    "app.modules.document.dispatcher.KafkaDocumentConversionDispatcher",
    FakeKafkaDocumentConversionDispatcher,
)
```

Update expected calls:

```python
("create_dispatcher", "producer"),
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && uv run python -m pytest tests/test_document_async_infrastructure.py::test_conversion_dispatcher_produces_kafka_event tests/test_document_resource_ownership.py -v
```

Expected: fail because dispatcher and runtime wiring are still Celery-based.

- [ ] **Step 3: Implement Kafka dispatcher and runtime wiring**

Create `backend/app/modules/document/dispatcher.py`:

```python
"""Document conversion dispatchers."""

from __future__ import annotations

from typing import Any

from app.modules.document.events import (
    DOCUMENT_CONVERT_REQUESTED_TOPIC,
    DocumentConvertRequested,
)


class KafkaDocumentConversionDispatcher:
    """Dispatch document conversion requests to Kafka."""

    def __init__(self, producer: Any) -> None:
        self._producer = producer

    async def dispatch(self, doc_id: int) -> None:
        event = DocumentConvertRequested.create(doc_id=doc_id)
        delivery = await self._producer.produce(
            topic=DOCUMENT_CONVERT_REQUESTED_TOPIC,
            key=event.doc_id.encode(),
            value=event.to_json().encode(),
        )
        await delivery.wait()
```

In `backend/app/modules/document/workflow.py`, change:

```python
conversion_dispatcher.dispatch(document.doc_id)
```

to:

```python
await conversion_dispatcher.dispatch(document.doc_id)
```

and update the log message to:

```python
logger.exception("failed to dispatch document conversion event", extra={"doc_id": document.doc_id})
```

In `backend/app/api/deps.py`, replace the Celery import and dispatcher construction:

```python
from app.infrastructure.kafka import create_kafka_producer
from app.modules.document.dispatcher import KafkaDocumentConversionDispatcher
```

and:

```python
conversion_dispatcher=KafkaDocumentConversionDispatcher(
    create_kafka_producer(settings.kafka_bootstrap_servers),
),
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend && uv run python -m pytest tests/test_document_async_infrastructure.py::test_conversion_dispatcher_produces_kafka_event tests/test_document_resource_ownership.py tests/test_document_plain_text_upload.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/document/dispatcher.py backend/app/modules/document/workflow.py backend/app/api/deps.py backend/tests/test_document_async_infrastructure.py backend/tests/test_document_resource_ownership.py
git commit -m "feat: dispatch document conversions through kafka"
```

### Task 4: Document Conversion Consumer Runner

**Files:**
- Modify: `backend/tests/test_document_async_infrastructure.py`
- Create: `backend/app/modules/document/workers/__init__.py`
- Create: `backend/app/modules/document/workers/conversion.py`
- Delete: `backend/app/modules/document/tasks.py`

- [ ] **Step 1: Write failing consumer runner tests**

Update worker imports in `backend/tests/test_document_async_infrastructure.py` from:

```python
from app.modules.document import tasks
```

to:

```python
from app.modules.document.workers import conversion
```

Update monkeypatch targets from `tasks` to `conversion`.

Add tests:

```python
@pytest.mark.asyncio
async def test_handle_document_conversion_event_commits_after_success(monkeypatch):
    from app.modules.document.workers import conversion

    calls = []

    class FakeMessage:
        def value(self):
            return b'{"event_id":"event-1","event_type":"document.convert.requested","doc_id":"42","occurred_at":"2026-07-02T00:00:00Z"}'

    class FakeConsumer:
        async def commit(self, message=None):
            calls.append(("commit", message))

    async def fake_run_document_conversion(doc_id):
        calls.append(("convert", doc_id))

    monkeypatch.setattr(conversion, "run_document_conversion", fake_run_document_conversion)

    message = FakeMessage()
    await conversion.handle_document_conversion_message(message=message, consumer=FakeConsumer())

    assert calls == [("convert", 42), ("commit", message)]


@pytest.mark.asyncio
async def test_handle_document_conversion_event_does_not_commit_on_conversion_failure(monkeypatch):
    from app.modules.document.workers import conversion

    class FakeMessage:
        def value(self):
            return b'{"event_id":"event-1","event_type":"document.convert.requested","doc_id":"42","occurred_at":"2026-07-02T00:00:00Z"}'

    class FakeConsumer:
        async def commit(self, message=None):
            raise AssertionError("must not commit failed conversion")

    async def fail_conversion(doc_id):
        raise RuntimeError("conversion failed")

    monkeypatch.setattr(conversion, "run_document_conversion", fail_conversion)

    with pytest.raises(RuntimeError, match="conversion failed"):
        await conversion.handle_document_conversion_message(message=FakeMessage(), consumer=FakeConsumer())
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && uv run python -m pytest tests/test_document_async_infrastructure.py -v
```

Expected: fail because document worker package and consumer handler do not exist.

- [ ] **Step 3: Implement document conversion worker**

Create `backend/app/modules/document/workers/__init__.py`:

```python
"""Document module Kafka workers."""
```

Create `backend/app/modules/document/workers/conversion.py` by moving the non-Celery runtime code from `tasks.py` and adding Kafka handling:

```python
"""Document conversion Kafka worker."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import get_settings
from app.infrastructure.kafka import create_kafka_consumer
from app.modules.document.events import (
    DOCUMENT_CONVERT_GROUP_ID,
    DOCUMENT_CONVERT_REQUESTED_TOPIC,
    DocumentConvertRequested,
)

logger = logging.getLogger(__name__)


async def run_document_conversion_consumer() -> None:
    settings = get_settings()
    consumer = create_kafka_consumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=DOCUMENT_CONVERT_GROUP_ID,
    )
    await consumer.subscribe([DOCUMENT_CONVERT_REQUESTED_TOPIC])
    try:
        while True:
            message = await consumer.poll(timeout=1.0)
            if message is None:
                continue
            error = message.error()
            if error is not None:
                logger.warning("kafka consumer error", extra={"error": str(error)})
                continue
            await handle_document_conversion_message(message=message, consumer=consumer)
    finally:
        await consumer.close()


async def handle_document_conversion_message(*, message: Any, consumer: Any) -> None:
    event = DocumentConvertRequested.from_json(message.value())
    await run_document_conversion(doc_id=event.doc_id_int())
    await consumer.commit(message=message)


async def run_document_conversion(doc_id: int) -> None:
    from app.infrastructure.redis_lock import create_redis_client, document_conversion_lock

    settings = get_settings()
    redis_client = create_redis_client(settings.redis_url)
    try:
        lock = document_conversion_lock(
            redis_client=redis_client,
            doc_id=doc_id,
            expire_seconds=settings.document_convert_lock_expire_seconds,
        )
        if not lock.acquire(blocking=False):
            return
        try:
            await run_locked_document_conversion(doc_id=doc_id, settings=settings)
        finally:
            lock.release()
    finally:
        redis_client.close()


async def run_locked_document_conversion(*, doc_id: int, settings: Any) -> None:
    from app.db.session import close_engine, get_session_factory, init_engine
    from app.modules.document.processing import convert_uploaded_document
    from app.modules.document.repository import DocumentRepository

    await init_engine(settings.database_url)
    mineru_client = _LazyMinerUClient(settings)
    try:
        await convert_uploaded_document(
            doc_id=doc_id,
            document_repository=DocumentRepository(get_session_factory()),
            storage=_LazyDocumentStorage(settings),
            mineru_client=mineru_client,
        )
    finally:
        await mineru_client.aclose()
        await close_engine()
```

Copy `_LazyDocumentStorage` and `_LazyMinerUClient` from the old `tasks.py` into the same file unchanged. Delete `backend/app/modules/document/tasks.py` after tests are updated.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend && uv run python -m pytest tests/test_document_async_infrastructure.py tests/test_document_conversion_worker.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/document/workers backend/tests/test_document_async_infrastructure.py backend/tests/test_document_conversion_worker.py
git rm backend/app/modules/document/tasks.py
git commit -m "feat: consume document conversions from kafka"
```

### Task 5: Worker Host Entrypoint

**Files:**
- Create: `backend/tests/test_kafka_worker_host.py`
- Create: `backend/app/workers/__init__.py`
- Create: `backend/app/workers/kafka_worker.py`

- [ ] **Step 1: Write failing worker host tests**

Create `backend/tests/test_kafka_worker_host.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_start_worker_consumers_runs_document_convert(monkeypatch):
    from app.workers import kafka_worker

    calls = []

    class FakeTaskGroup:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def create_task(self, coroutine):
            calls.append(coroutine)
            coroutine.close()

    async def fake_document_consumer():
        return None

    monkeypatch.setattr(kafka_worker.asyncio, "TaskGroup", FakeTaskGroup)
    monkeypatch.setattr(kafka_worker, "run_document_conversion_consumer", fake_document_consumer)

    await kafka_worker.start_worker_consumers()

    assert len(calls) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && uv run python -m pytest tests/test_kafka_worker_host.py -v
```

Expected: fail because `app.workers.kafka_worker` does not exist.

- [ ] **Step 3: Implement worker host**

Create `backend/app/workers/__init__.py`:

```python
"""Process entrypoints for background workers."""
```

Create `backend/app/workers/kafka_worker.py`:

```python
"""Kafka worker process entrypoint."""

from __future__ import annotations

import asyncio

from app.modules.document.workers.conversion import run_document_conversion_consumer


async def start_worker_consumers() -> None:
    async with asyncio.TaskGroup() as task_group:
        task_group.create_task(run_document_conversion_consumer())


async def main() -> None:
    await start_worker_consumers()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend && uv run python -m pytest tests/test_kafka_worker_host.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/workers backend/tests/test_kafka_worker_host.py
git commit -m "feat: add kafka worker host"
```

### Task 6: Remove Celery References and Update Existing Tests

**Files:**
- Delete: `backend/app/infrastructure/celery.py`
- Modify: all tests and docs with stale Celery runtime assertions.

- [ ] **Step 1: Write failing removal checks**

Run:

```bash
rg -n "celery|Celery|CELERY" backend Makefile docker-compose.yml
```

Expected before cleanup: matches remain in application code or tests.

- [ ] **Step 2: Remove stale references**

Delete `backend/app/infrastructure/celery.py`.

Update any test imports or source assertions that still mention:

```text
app.infrastructure.celery
app.modules.document.tasks
CeleryDocumentConversionDispatcher
CELERY_BROKER_URL
CELERY_RESULT_BACKEND
celery -A
```

Expected replacements:

```text
app.infrastructure.kafka
app.modules.document.dispatcher
app.modules.document.workers.conversion
KafkaDocumentConversionDispatcher
KAFKA_BOOTSTRAP_SERVERS
DOCUMENT_CONVERT_REQUESTED_TOPIC
```

- [ ] **Step 3: Verify no runtime Celery references remain**

Run:

```bash
rg -n "celery|Celery|CELERY" backend Makefile docker-compose.yml
```

Expected: no matches in backend runtime, dependency, tests, Makefile, or Compose files. Historical design docs may still mention Celery and do not need to be rewritten.

- [ ] **Step 4: Run targeted tests**

Run:

```bash
cd backend && uv run python -m pytest tests/test_document_async_infrastructure.py tests/test_document_config.py tests/test_document_resource_ownership.py tests/test_backend_makefile.py tests/test_kafka_worker_host.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend tests Makefile docker-compose.yml
git add -u backend
git commit -m "refactor: remove celery document worker path"
```

### Task 7: Full Verification

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run full backend test suite**

Run:

```bash
cd backend && uv run python -m pytest
```

Expected: all tests pass.

- [ ] **Step 2: Verify repository status**

Run:

```bash
git status --short
```

Expected: clean after commits.

- [ ] **Step 3: Verify dependency tree no longer contains Celery**

Run:

```bash
cd backend && uv run python - <<'PY'
import importlib.util
print("celery", importlib.util.find_spec("celery"))
print("confluent_kafka", importlib.util.find_spec("confluent_kafka") is not None)
PY
```

Expected:

```text
celery None
confluent_kafka True
```

---

## Self-Review

- Spec coverage:
  - Native Kafka client: Tasks 1 and 2.
  - Remove Celery: Tasks 1, 4, and 6.
  - Module-local document workers: Task 4.
  - Thin global worker host: Task 5.
  - Manual commit after success: Task 4.
  - Local self-hosted Kafka: Task 1.
  - Tests for dispatcher, event, worker, config, Makefile: Tasks 1 through 6.
- Placeholder scan:
  - No `TBD`, `TODO`, or unspecified "add appropriate handling" steps remain.
- Type consistency:
  - `KafkaDocumentConversionDispatcher.dispatch()` is async and `workflow.upload_document()` awaits it.
  - `DocumentConvertRequested.doc_id` is serialized as `str`, and worker converts via `doc_id_int()`.
  - `run_document_conversion_consumer()` lives in `app.modules.document.workers.conversion`.
