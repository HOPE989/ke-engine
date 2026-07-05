from types import SimpleNamespace

import pytest

from app.modules.document.models import DocumentStatus


class FakeMessage:
    def value(self):
        return (
            b'{"event_id":"event-1","event_type":"document.embed_store.requested",'
            b'"doc_id":"42","occurred_at":"2026-07-02T00:00:00Z"}'
        )

    def error(self):
        return None


class FakeConsumer:
    def __init__(self):
        self.commits = []

    async def commit(self, message=None):
        self.commits.append(message)


class FakeRepository:
    def __init__(self, document):
        self.document = document
        self.get_calls = []

    async def get_document(self, doc_id):
        self.get_calls.append(doc_id)
        return self.document


def _document(status):
    return SimpleNamespace(doc_id=42, status=status)


@pytest.mark.asyncio
async def test_vector_storage_consumer_subscribes_to_topic_and_group(monkeypatch):
    from app.modules.document.workers import vector_storage

    calls = []

    class FakeKafkaConsumer:
        async def subscribe(self, topics):
            calls.append(("subscribe", topics))

        async def poll(self, *, timeout):
            calls.append(("poll", timeout))
            raise RuntimeError("stop consumer")

        async def close(self):
            calls.append(("close", None))

    def fake_create_kafka_consumer(*, bootstrap_servers, group_id):
        calls.append(("create_consumer", bootstrap_servers, group_id))
        return FakeKafkaConsumer()

    monkeypatch.setattr(
        vector_storage,
        "get_settings",
        lambda: SimpleNamespace(kafka_bootstrap_servers="kafka.example:9092"),
    )
    monkeypatch.setattr(vector_storage, "create_kafka_consumer", fake_create_kafka_consumer)

    with pytest.raises(RuntimeError, match="stop consumer"):
        await vector_storage.run_document_vector_storage_consumer()

    assert calls[:3] == [
        ("create_consumer", "kafka.example:9092", "ke-engine-document-embed-store"),
        ("subscribe", ["document.embed_store.requested"]),
        ("poll", 1.0),
    ]


@pytest.mark.asyncio
async def test_handle_vector_storage_message_commits_after_success(monkeypatch):
    from app.modules.document.workers import vector_storage

    calls = []

    async def fake_run_document_vector_storage(doc_id):
        calls.append(doc_id)
        return True

    monkeypatch.setattr(
        vector_storage,
        "run_document_vector_storage",
        fake_run_document_vector_storage,
    )
    consumer = FakeConsumer()
    message = FakeMessage()

    await vector_storage.handle_document_vector_storage_message(
        message=message,
        consumer=consumer,
    )

    assert calls == [42]
    assert consumer.commits == [message]


@pytest.mark.asyncio
async def test_handle_vector_storage_message_does_not_commit_retryable_failure(monkeypatch):
    from app.modules.document.workers import vector_storage

    async def fake_run_document_vector_storage(doc_id):
        return False

    monkeypatch.setattr(
        vector_storage,
        "run_document_vector_storage",
        fake_run_document_vector_storage,
    )
    consumer = FakeConsumer()

    await vector_storage.handle_document_vector_storage_message(
        message=FakeMessage(),
        consumer=consumer,
    )

    assert consumer.commits == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "document",
    [
        None,
        _document(DocumentStatus.VECTOR_STORED.value),
        _document(DocumentStatus.CONVERTED.value),
    ],
)
async def test_vector_storage_event_terminal_business_states_commit_without_work(
    monkeypatch,
    document,
):
    from app.modules.document.workers import vector_storage

    calls = []

    async def unexpected_store_document_vectors(**kwargs):
        calls.append(kwargs)
        raise AssertionError("terminal states must not run vector storage")

    monkeypatch.setattr(vector_storage, "store_document_vectors", unexpected_store_document_vectors)

    should_commit = await vector_storage.handle_document_vector_storage_event(
        doc_id=42,
        document_repository=FakeRepository(document),
        vector_store=object(),
        lock=object(),
    )

    assert should_commit is True
    assert calls == []


@pytest.mark.asyncio
async def test_vector_storage_event_success_for_chunked_document_commits(monkeypatch):
    from app.modules.document.workers import vector_storage

    calls = []

    async def fake_store_document_vectors(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(vector_storage, "store_document_vectors", fake_store_document_vectors)
    repository = FakeRepository(_document(DocumentStatus.CHUNKED.value))
    vector_store = object()
    lock = object()

    should_commit = await vector_storage.handle_document_vector_storage_event(
        doc_id=42,
        document_repository=repository,
        vector_store=vector_store,
        lock=lock,
    )

    assert should_commit is True
    assert calls == [
        {
            "doc_id": 42,
            "document_repository": repository,
            "vector_store": vector_store,
            "lock": lock,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        "busy",
        RuntimeError("openai down"),
        OSError("elasticsearch down"),
        "id_mismatch",
        "double_check",
    ],
)
async def test_vector_storage_event_retryable_failures_do_not_commit(monkeypatch, error):
    from app.modules.document import vector_storage as workflow
    from app.modules.document.vector_store import VectorStoreIdCountMismatch
    from app.modules.document.workers import vector_storage

    if error == "busy":
        raised = workflow.VectorStorageLockBusy()
    elif error == "id_mismatch":
        raised = VectorStoreIdCountMismatch(returned_ids=["orphan-id"])
    elif error == "double_check":
        raised = workflow.VectorStorageIncomplete()
    else:
        raised = error

    async def fail_store_document_vectors(**kwargs):
        raise raised

    monkeypatch.setattr(vector_storage, "store_document_vectors", fail_store_document_vectors)

    should_commit = await vector_storage.handle_document_vector_storage_event(
        doc_id=42,
        document_repository=FakeRepository(_document(DocumentStatus.CHUNKED.value)),
        vector_store=object(),
        lock=object(),
    )

    assert should_commit is False
