from types import SimpleNamespace

import pytest


def test_snowflake_id_generator_returns_monotonic_64_bit_ids(monkeypatch):
    from app.infrastructure.snowflake import SnowflakeIdGenerator

    timestamps = iter([1_800_000_000_000, 1_800_000_000_000, 1_800_000_000_001])
    monkeypatch.setattr(
        "app.infrastructure.snowflake.current_time_millis",
        lambda: next(timestamps),
    )
    generator = SnowflakeIdGenerator(worker_id=7)

    first = generator.next_id()
    second = generator.next_id()
    third = generator.next_id()

    assert first < second < third
    assert first.bit_length() <= 63


@pytest.mark.asyncio
async def test_conversion_dispatcher_produces_kafka_event():
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


class FakeRedisClient:
    def __init__(self, calls):
        self.calls = calls

    def close(self):
        self.calls.append(("redis_close", None))


class FakeLock:
    def __init__(self, calls, *, acquired=True):
        self.calls = calls
        self.acquired = acquired

    def acquire(self, *, blocking):
        self.calls.append(("lock_acquire", blocking))
        return self.acquired

    def release(self):
        self.calls.append(("lock_release", None))


class FakeTaskRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def get_document(self, doc_id):
        return SimpleNamespace(
            doc_id=doc_id,
            doc_title="guide.md",
            upload_user="alice",
            accessible_by="team-a",
            file_type="plain_text",
            doc_url="https://files.example.com/documents/42/original/guide.md",
            status="uploaded",
        )

    async def start_converting(self, *, doc_id):
        return None

    async def mark_converted(self, *, doc_id, converted_doc_url, expected_status):
        return None


def _worker_settings():
    return SimpleNamespace(
        redis_url="redis://redis.example:6379/0",
        database_url="postgresql+asyncpg://user:pass@localhost:5432/app",
        document_convert_lock_expire_seconds=120,
        minio_bucket="documents",
        minio_public_base_url="https://files.example.com",
    )


@pytest.mark.asyncio
async def test_worker_skips_runtime_initialization_when_document_lock_is_busy(monkeypatch):
    from app.modules.document import tasks

    calls = []
    monkeypatch.setattr(tasks, "get_settings", _worker_settings)
    monkeypatch.setattr(
        "app.infrastructure.redis_lock.create_redis_client",
        lambda redis_url: FakeRedisClient(calls),
    )
    monkeypatch.setattr(
        "app.infrastructure.redis_lock.document_conversion_lock",
        lambda **kwargs: FakeLock(calls, acquired=False),
    )

    async def unexpected_init_engine(database_url):
        raise AssertionError("busy lock must not initialize database runtime")

    monkeypatch.setattr("app.db.session.init_engine", unexpected_init_engine)
    monkeypatch.setattr(
        "app.infrastructure.mineru.create_mineru_client",
        lambda settings: (_ for _ in ()).throw(
            AssertionError("busy lock must not create MinerU client")
        ),
    )
    monkeypatch.setattr(
        "app.infrastructure.minio.get_minio_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("busy lock must not create MinIO client")
        ),
    )

    await tasks._run_document_conversion(doc_id=42)

    assert calls == [
        ("lock_acquire", False),
        ("redis_close", None),
    ]


@pytest.mark.asyncio
async def test_worker_plain_text_path_does_not_initialize_pdf_runtime(monkeypatch):
    from app.modules.document import tasks

    calls = []
    monkeypatch.setattr(tasks, "get_settings", _worker_settings)
    monkeypatch.setattr(
        "app.infrastructure.redis_lock.create_redis_client",
        lambda redis_url: FakeRedisClient(calls),
    )
    monkeypatch.setattr(
        "app.infrastructure.redis_lock.document_conversion_lock",
        lambda **kwargs: FakeLock(calls, acquired=True),
    )

    async def fake_init_engine(database_url):
        calls.append(("init_engine", database_url))

    async def fake_close_engine():
        calls.append(("close_engine", None))

    monkeypatch.setattr("app.db.session.init_engine", fake_init_engine)
    monkeypatch.setattr("app.db.session.close_engine", fake_close_engine)
    monkeypatch.setattr("app.db.session.get_session_factory", lambda: object())
    monkeypatch.setattr(
        "app.modules.document.repository.DocumentRepository",
        FakeTaskRepository,
    )
    monkeypatch.setattr(
        "app.infrastructure.mineru.create_mineru_client",
        lambda settings: (_ for _ in ()).throw(
            AssertionError("plain text conversion must not create MinerU client")
        ),
    )
    monkeypatch.setattr(
        "app.infrastructure.minio.get_minio_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("plain text conversion must not create MinIO client")
        ),
    )
    monkeypatch.setattr(
        "app.infrastructure.minio.ensure_minio_bucket",
        lambda client, bucket: (_ for _ in ()).throw(
            AssertionError("worker must not ensure MinIO bucket per task")
        ),
    )

    await tasks._run_document_conversion(doc_id=42)

    assert calls == [
        ("lock_acquire", False),
        ("init_engine", "postgresql+asyncpg://user:pass@localhost:5432/app"),
        ("close_engine", None),
        ("lock_release", None),
        ("redis_close", None),
    ]
