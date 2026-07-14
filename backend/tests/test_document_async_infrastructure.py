import asyncio
import logging
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
    from app.domains.document.components import dispatcher

    calls = []

    class FakeProducer:
        def __init__(self):
            self.delivery = None

        async def produce(self, *, topic, key, value):
            calls.append(("produce", topic, key, value))
            delivery = asyncio.Future()
            self.delivery = delivery
            return delivery

        async def flush(self):
            calls.append(("flush", None))
            self.delivery.set_result(SimpleNamespace(topic="document.convert.requested"))

    await asyncio.wait_for(dispatcher.KafkaDocumentConversionDispatcher(FakeProducer()).dispatch(42), timeout=0.1)

    assert calls[0][0] == "produce"
    assert calls[0][1] == "document.convert.requested"
    assert calls[0][2] == b"42"
    assert b'"event_type":"document.convert.requested"' in calls[0][3]
    assert calls[1] == ("flush", None)


@pytest.mark.asyncio
async def test_embed_store_dispatcher_produces_kafka_event():
    from app.domains.document.components import dispatcher

    calls = []

    class FakeProducer:
        def __init__(self):
            self.delivery = None

        async def produce(self, *, topic, key, value):
            calls.append(("produce", topic, key, value))
            delivery = asyncio.Future()
            self.delivery = delivery
            return delivery

        async def flush(self):
            calls.append(("flush", None))
            self.delivery.set_result(SimpleNamespace(topic="document.embed_store.requested"))

    await asyncio.wait_for(
        dispatcher.KafkaDocumentEmbedStoreDispatcher(FakeProducer()).dispatch(42),
        timeout=0.1,
    )

    assert calls[0][0] == "produce"
    assert calls[0][1] == "document.embed_store.requested"
    assert calls[0][2] == b"42"
    assert b'"event_type":"document.embed_store.requested"' in calls[0][3]
    assert calls[1] == ("flush", None)


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
    from app.domains.document.workers import conversion_consumer as conversion

    calls = []
    monkeypatch.setattr(
        "app.infrastructure.redis.document_conversion_lock",
        lambda **kwargs: FakeLock(calls, acquired=False),
    )

    async def unexpected_init_engine(database_url):
        raise AssertionError("busy lock must not initialize database runtime")

    monkeypatch.setattr("app.infrastructure.db.session.init_engine", unexpected_init_engine)
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

    await conversion.run_document_conversion(
        doc_id=42,
        runtime=SimpleNamespace(
            conversion=SimpleNamespace(
                redis_client=FakeRedisClient(calls),
                lock_expire_seconds=_worker_settings().document_convert_lock_expire_seconds,
            ),
        ),
    )

    assert calls == [("lock_acquire", False)]


@pytest.mark.asyncio
async def test_worker_plain_text_path_does_not_initialize_pdf_runtime(monkeypatch):
    from app.domains.document.workers import conversion_consumer as conversion

    calls = []
    monkeypatch.setattr(
        "app.infrastructure.redis.document_conversion_lock",
        lambda **kwargs: FakeLock(calls, acquired=True),
    )

    async def fake_init_engine(database_url):
        calls.append(("init_engine", database_url))

    async def fake_close_engine():
        calls.append(("close_engine", None))

    monkeypatch.setattr("app.infrastructure.db.session.init_engine", fake_init_engine)
    monkeypatch.setattr("app.infrastructure.db.session.close_engine", fake_close_engine)
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

    await conversion.run_document_conversion(
        doc_id=42,
        runtime=SimpleNamespace(
            conversion=SimpleNamespace(
                redis_client=FakeRedisClient(calls),
                lock_expire_seconds=_worker_settings().document_convert_lock_expire_seconds,
                repository=FakeTaskRepository(object()),
                storage=object(),
                mineru_client=object(),
                image_describer=object(),
                converter_factory=object(),
            ),
        ),
    )

    assert calls == [
        ("lock_acquire", False),
        ("lock_release", None),
    ]


@pytest.mark.asyncio
async def test_document_conversion_consumer_subscribes_without_managing_topics(monkeypatch, caplog):
    from app.domains.document.workers import conversion_consumer as conversion

    calls = []

    class FakeConsumer:
        async def subscribe(self, topics):
            calls.append(("subscribe", topics))

        async def poll(self, *, timeout):
            calls.append(("poll", timeout))
            raise RuntimeError("stop consumer")

        async def close(self):
            calls.append(("close", None))

    def fake_create_kafka_consumer(*, bootstrap_servers, group_id):
        calls.append(("create_consumer", bootstrap_servers, group_id))
        return FakeConsumer()

    monkeypatch.setattr(conversion, "create_kafka_consumer", fake_create_kafka_consumer)
    runtime = SimpleNamespace(settings=SimpleNamespace(kafka_bootstrap_servers="kafka.example:9092"))

    with caplog.at_level(logging.INFO, logger="app.domains.document.workers.conversion_consumer"):
        with pytest.raises(RuntimeError, match="stop consumer"):
            await conversion.run_document_conversion_consumer(runtime)

    assert calls[:3] == [
        ("create_consumer", "kafka.example:9092", "ke-engine-document-converter"),
        ("subscribe", ["document.convert.requested"]),
        ("poll", 1.0),
    ]
    assert (
        "document conversion kafka consumer subscribed topic=document.convert.requested "
        "group_id=ke-engine-document-converter"
    ) in caplog.text


@pytest.mark.asyncio
async def test_document_conversion_consumer_logs_kafka_error_details(monkeypatch, caplog):
    from app.domains.document.workers import conversion_consumer as conversion

    class FakeError:
        def __str__(self):
            return "KafkaError{code=UNKNOWN_TOPIC_OR_PART,str=missing topic}"

    class FakeMessage:
        def error(self):
            return FakeError()

    class FakeConsumer:
        def __init__(self):
            self.polls = 0

        async def subscribe(self, topics):
            return None

        async def poll(self, *, timeout):
            self.polls += 1
            if self.polls == 1:
                return FakeMessage()
            raise RuntimeError("stop consumer")

        async def close(self):
            return None

    monkeypatch.setattr(conversion, "create_kafka_consumer", lambda **kwargs: FakeConsumer())
    runtime = SimpleNamespace(settings=SimpleNamespace(kafka_bootstrap_servers="kafka.example:9092"))

    with caplog.at_level(logging.WARNING, logger="app.domains.document.workers.conversion_consumer"):
        with pytest.raises(RuntimeError, match="stop consumer"):
            await conversion.run_document_conversion_consumer(runtime)

    assert "UNKNOWN_TOPIC_OR_PART" in caplog.text


@pytest.mark.asyncio
async def test_handle_document_conversion_event_commits_after_success(monkeypatch, caplog):
    from app.domains.document.workers import conversion_consumer as conversion

    calls = []

    class FakeMessage:
        def value(self):
            return (
                b'{"event_id":"event-1","event_type":"document.convert.requested",'
                b'"doc_id":"42","occurred_at":"2026-07-02T00:00:00Z"}'
            )

    class FakeConsumer:
        async def commit(self, message=None):
            calls.append(("commit", message))

    runtime = object()

    async def fake_run_document_conversion(*, doc_id, runtime):
        calls.append(("convert", doc_id, runtime))

    monkeypatch.setattr(conversion, "run_document_conversion", fake_run_document_conversion)
    monotonic_times = iter([100.0, 100.125])
    monkeypatch.setattr(conversion.time, "perf_counter", lambda: next(monotonic_times))

    message = FakeMessage()
    with caplog.at_level(logging.INFO, logger="app.domains.document.workers.conversion_consumer"):
        await conversion.handle_document_conversion_message(
            message=message,
            consumer=FakeConsumer(),
            runtime=runtime,
        )

    assert calls == [("convert", 42, runtime), ("commit", message)]
    assert "processing document conversion message doc_id=42" in caplog.text
    assert "committed document conversion message doc_id=42 elapsed_ms=125.00" in caplog.text


@pytest.mark.asyncio
async def test_handle_document_conversion_event_does_not_commit_on_conversion_failure(monkeypatch, caplog):
    from app.domains.document.workers import conversion_consumer as conversion

    class FakeMessage:
        def value(self):
            return (
                b'{"event_id":"event-1","event_type":"document.convert.requested",'
                b'"doc_id":"42","occurred_at":"2026-07-02T00:00:00Z"}'
            )

    class FakeConsumer:
        async def commit(self, message=None):
            raise AssertionError("must not commit failed conversion")

    runtime = object()

    async def fail_conversion(*, doc_id, runtime):
        raise RuntimeError("conversion failed")

    monkeypatch.setattr(conversion, "run_document_conversion", fail_conversion)
    monotonic_times = iter([200.0, 200.25])
    monkeypatch.setattr(conversion.time, "perf_counter", lambda: next(monotonic_times))

    with caplog.at_level(logging.ERROR, logger="app.domains.document.workers.conversion_consumer"):
        with pytest.raises(RuntimeError, match="conversion failed"):
            await conversion.handle_document_conversion_message(
                message=FakeMessage(),
                consumer=FakeConsumer(),
                runtime=runtime,
            )

    assert "failed to handle document conversion message doc_id=42 elapsed_ms=250.00" in caplog.text
