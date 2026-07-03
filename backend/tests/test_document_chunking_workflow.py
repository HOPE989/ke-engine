from types import SimpleNamespace

import pytest

from app.modules.document.models import DocumentStatus


class FakeRepository:
    def __init__(self, document=None):
        self.document = document
        self.completed = []

    async def get_document(self, doc_id):
        return self.document

    async def complete_chunking(self, *, doc_id, segment_drafts):
        self.completed.append({"doc_id": doc_id, "segment_drafts": segment_drafts})

    async def count_embeddable_segments(self, *, doc_id):
        return 3


class FailingCompleteRepository(FakeRepository):
    async def complete_chunking(self, *, doc_id, segment_drafts):
        from app.modules.document.errors import ChunkPersistenceFailed

        self.completed.append({"doc_id": doc_id, "segment_drafts": segment_drafts})
        raise ChunkPersistenceFailed()


class FakeStorage:
    bucket = "documents"
    public_base_url = "https://files.example.com"

    def __init__(self, payload=b"# Guide\ncontent", download_error=None):
        self.payload = payload
        self.download_error = download_error
        self.downloaded_keys = []

    async def download_bytes(self, *, object_key):
        self.downloaded_keys.append(object_key)
        if self.download_error is not None:
            raise self.download_error
        return self.payload


class FakeLock:
    def __init__(self, *, acquired=True, acquire_error=None):
        self.acquired = acquired
        self.acquire_error = acquire_error
        self.acquire_calls = []
        self.releases = 0

    def acquire(self, *, blocking):
        self.acquire_calls.append({"blocking": blocking})
        if self.acquire_error is not None:
            raise self.acquire_error
        return self.acquired

    def release(self):
        self.releases += 1


class FakeIdGenerator:
    def __init__(self):
        self.next_value = 1000

    def next_id(self):
        self.next_value += 1
        return self.next_value


def _document(**overrides):
    values = {
        "doc_id": 42,
        "doc_title": "guide.md",
        "status": DocumentStatus.CONVERTED.value,
        "converted_doc_url": (
            "https://files.example.com/documents/documents/42/converted/document.md"
        ),
        "accessible_by": "team-a",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def _chunk_document(**overrides):
    from app.modules.document.workflow import chunk_document

    values = {
        "doc_id": 42,
        "document_repository": FakeRepository(_document()),
        "storage": FakeStorage(),
        "id_generator": FakeIdGenerator(),
        "lock": FakeLock(),
        "chunk_size": 100,
        "overlap": 0,
    }
    values.update(overrides)
    return await chunk_document(**values)


@pytest.mark.asyncio
async def test_chunk_workflow_rejects_missing_document_before_locking():
    from app.modules.document.errors import DocumentNotFound

    lock = FakeLock()

    with pytest.raises(DocumentNotFound):
        await _chunk_document(document_repository=FakeRepository(None), lock=lock)

    assert lock.acquire_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        DocumentStatus.INIT.value,
        DocumentStatus.UPLOADED.value,
        DocumentStatus.CONVERTING.value,
    ],
)
async def test_chunk_workflow_rejects_non_converted_document(status):
    from app.modules.document.errors import DocumentStateConflict

    repository = FakeRepository(_document(status=status))
    lock = FakeLock()

    with pytest.raises(DocumentStateConflict):
        await _chunk_document(document_repository=repository, lock=lock)

    assert lock.acquire_calls == []


@pytest.mark.asyncio
async def test_chunk_workflow_returns_already_chunked_document_without_locking():
    repository = FakeRepository(_document(status=DocumentStatus.CHUNKED.value))
    lock = FakeLock()

    response = await _chunk_document(document_repository=repository, lock=lock)

    assert response.doc_id == "42"
    assert response.status == DocumentStatus.CHUNKED.value
    assert response.segment_count == 3
    assert repository.completed == []
    assert lock.acquire_calls == []


@pytest.mark.asyncio
async def test_chunk_workflow_rejects_converted_document_without_url():
    from app.modules.document.errors import DocumentStateConflict

    repository = FakeRepository(_document(converted_doc_url=None))

    with pytest.raises(DocumentStateConflict):
        await _chunk_document(document_repository=repository)



@pytest.mark.asyncio
async def test_chunk_workflow_rejects_invalid_converted_url():
    from app.modules.document.errors import DocumentStateConflict

    repository = FakeRepository(
        _document(converted_doc_url="https://other.example.com/documents/documents/42.md")
    )

    with pytest.raises(DocumentStateConflict):
        await _chunk_document(document_repository=repository)

    assert repository.completed == []


@pytest.mark.asyncio
async def test_chunk_workflow_rejects_busy_lock_without_starting_chunking():
    from app.modules.document.errors import DocumentStateConflict

    repository = FakeRepository(_document())
    lock = FakeLock(acquired=False)

    with pytest.raises(DocumentStateConflict):
        await _chunk_document(document_repository=repository, lock=lock)

    assert lock.acquire_calls == [{"blocking": False}]


@pytest.mark.asyncio
async def test_chunk_workflow_success_persists_segments_and_returns_response():
    repository = FakeRepository(_document())
    lock = FakeLock()
    storage = FakeStorage(payload=b"# Guide\nshort content")

    response = await _chunk_document(
        document_repository=repository,
        storage=storage,
        lock=lock,
        id_generator=FakeIdGenerator(),
        chunk_size=100,
        overlap=0,
    )

    assert response.doc_id == "42"
    assert response.status == DocumentStatus.CHUNKED.value
    assert response.segment_count == 1
    assert len(repository.completed) == 1
    assert repository.completed[0]["doc_id"] == 42
    assert len(repository.completed[0]["segment_drafts"]) == 1
    assert repository.completed[0]["segment_drafts"][0].text == "short content"
    assert storage.downloaded_keys == ["documents/42/converted/document.md"]
    assert lock.releases == 1


@pytest.mark.asyncio
async def test_chunk_workflow_zero_segment_result_still_marks_chunked():
    repository = FakeRepository(_document())

    response = await _chunk_document(
        document_repository=repository,
        storage=FakeStorage(payload=b"   "),
        id_generator=FakeIdGenerator(),
        chunk_size=100,
        overlap=0,
    )

    assert response.doc_id == "42"
    assert response.status == DocumentStatus.CHUNKED.value
    assert response.segment_count == 0
    assert repository.completed == [{"doc_id": 42, "segment_drafts": []}]


@pytest.mark.asyncio
async def test_chunk_workflow_maps_redis_unavailable_before_processing():
    from app.modules.document.errors import ChunkLockUnavailable

    repository = FakeRepository(_document())

    with pytest.raises(ChunkLockUnavailable):
        await _chunk_document(
            document_repository=repository,
            lock=FakeLock(acquire_error=OSError("redis down")),
        )

@pytest.mark.asyncio
async def test_chunk_workflow_leaves_converted_on_markdown_download_failure():
    from app.modules.document.errors import ConvertedMarkdownUnavailable

    repository = FakeRepository(_document())

    with pytest.raises(ConvertedMarkdownUnavailable):
        await _chunk_document(
            document_repository=repository,
            storage=FakeStorage(download_error=OSError("minio down")),
        )

    assert repository.completed == []


@pytest.mark.asyncio
async def test_chunk_workflow_leaves_converted_on_non_utf8_markdown():
    from app.modules.document.errors import ConvertedMarkdownInvalid

    repository = FakeRepository(_document())

    with pytest.raises(ConvertedMarkdownInvalid):
        await _chunk_document(
            document_repository=repository,
            storage=FakeStorage(payload=b"\xff\xfe"),
        )

    assert repository.completed == []


@pytest.mark.asyncio
async def test_chunk_workflow_maps_splitter_failure_without_rollback(monkeypatch):
    from app.modules.document import workflow
    from app.modules.document.errors import ChunkSplittingFailed

    def fail_splitter(markdown, *, chunk_size, overlap, id_generator):
        raise RuntimeError("split failed")

    repository = FakeRepository(_document())
    monkeypatch.setattr(workflow, "split_markdown_into_chunks", fail_splitter)

    with pytest.raises(ChunkSplittingFailed):
        await _chunk_document(document_repository=repository)

    assert repository.completed == []


@pytest.mark.asyncio
async def test_chunk_workflow_maps_persistence_failure_without_rollback():
    from app.modules.document.errors import ChunkPersistenceFailed

    repository = FailingCompleteRepository(_document())

    with pytest.raises(ChunkPersistenceFailed):
        await _chunk_document(document_repository=repository)

    assert repository.completed
