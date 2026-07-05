from types import SimpleNamespace

import pytest


class FakeTransaction:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.begins += 1
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.session.commits += 1
        else:
            self.session.rollbacks += 1
        return False


class FakeSession:
    def __init__(self):
        self.begins = 0
        self.commits = 0
        self.rollbacks = 0

    def begin(self):
        return FakeTransaction(self)


class FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeRepository:
    def __init__(
        self,
        *,
        batches,
        remaining_count=0,
        mark_error=None,
        complete_error=None,
    ):
        self.session_obj = FakeSession()
        self.batches = list(batches)
        self.remaining_count = remaining_count
        self.mark_error = mark_error
        self.complete_error = complete_error
        self.session_opened = 0
        self.list_calls = []
        self.mark_calls = []
        self.count_calls = []
        self.complete_calls = []

    def session(self):
        self.session_opened += 1
        return FakeSessionContext(self.session_obj)

    async def list_pending_embeddable_segments(self, *, session, doc_id, limit=100):
        assert session is self.session_obj
        self.list_calls.append({"doc_id": doc_id, "limit": limit})
        if self.batches:
            return self.batches.pop(0)
        return []

    async def mark_segments_vector_stored(self, *, session, segment_embedding_ids):
        assert session is self.session_obj
        self.mark_calls.append(dict(segment_embedding_ids))
        if self.mark_error is not None:
            raise self.mark_error

    async def count_pending_embeddable_segments(self, *, session, doc_id):
        assert session is self.session_obj
        self.count_calls.append(doc_id)
        return self.remaining_count

    async def mark_document_vector_stored(self, *, session, doc_id):
        assert session is self.session_obj
        self.complete_calls.append(doc_id)
        if self.complete_error is not None:
            raise self.complete_error


class FakeVectorStore:
    def __init__(self, *, id_batches=None, add_errors=None):
        self.id_batches = list(id_batches or [])
        self.add_errors = list(add_errors or [])
        self.add_calls = []
        self.deleted_doc_ids = []
        self.deleted_ids = []

    async def add_segments(self, segments):
        self.add_calls.append(list(segments))
        if self.add_errors:
            raise self.add_errors.pop(0)
        return self.id_batches.pop(0)

    async def delete_by_doc_id(self, doc_id):
        self.deleted_doc_ids.append(doc_id)

    async def delete_by_ids(self, ids):
        self.deleted_ids.append(list(ids))


class FakeLock:
    def __init__(self, *, acquired=True, acquire_error=None):
        self.acquired = acquired
        self.acquire_error = acquire_error
        self.acquire_calls = []
        self.releases = 0

    def acquire(self, *, blocking):
        self.acquire_calls.append(blocking)
        if self.acquire_error is not None:
            raise self.acquire_error
        return self.acquired

    def release(self):
        self.releases += 1


def _segment(segment_id, *, skip_embedding=False):
    return SimpleNamespace(
        id=segment_id,
        text=f"segment-{segment_id}",
        skip_embedding=skip_embedding,
    )


@pytest.mark.asyncio
async def test_vector_storage_success_scans_fixed_first_page_and_completes_document():
    from app.modules.document.vector_storage import store_document_vectors

    repository = FakeRepository(
        batches=[
            [_segment(1), _segment(2)],
            [_segment(3)],
            [],
        ],
        remaining_count=0,
    )
    vector_store = FakeVectorStore(id_batches=[["es-1", "es-2"], ["es-3"]])
    lock = FakeLock()

    await store_document_vectors(
        doc_id=42,
        document_repository=repository,
        vector_store=vector_store,
        lock=lock,
    )

    assert lock.acquire_calls == [False]
    assert lock.releases == 1
    assert vector_store.deleted_doc_ids == [42]
    assert [[segment.id for segment in call] for call in vector_store.add_calls] == [[1, 2], [3]]
    assert repository.mark_calls == [{1: "es-1", 2: "es-2"}, {3: "es-3"}]
    assert repository.list_calls == [
        {"doc_id": 42, "limit": 100},
        {"doc_id": 42, "limit": 100},
        {"doc_id": 42, "limit": 100},
    ]
    assert repository.count_calls == [42]
    assert repository.complete_calls == [42]
    assert repository.session_obj.commits == 1
    assert repository.session_obj.rollbacks == 0


@pytest.mark.asyncio
async def test_vector_storage_zero_embeddable_or_only_skipped_segments_completes_without_model_calls():
    from app.modules.document.vector_storage import store_document_vectors

    repository = FakeRepository(batches=[[]], remaining_count=0)
    vector_store = FakeVectorStore()

    await store_document_vectors(
        doc_id=42,
        document_repository=repository,
        vector_store=vector_store,
        lock=FakeLock(),
    )

    assert vector_store.add_calls == []
    assert repository.mark_calls == []
    assert repository.count_calls == [42]
    assert repository.complete_calls == [42]
    assert repository.session_obj.commits == 1


@pytest.mark.asyncio
async def test_vector_storage_busy_lock_does_not_open_transaction_or_cleanup():
    from app.modules.document import vector_storage

    repository = FakeRepository(batches=[[]])
    vector_store = FakeVectorStore()

    with pytest.raises(vector_storage.VectorStorageLockBusy):
        await vector_storage.store_document_vectors(
            doc_id=42,
            document_repository=repository,
            vector_store=vector_store,
            lock=FakeLock(acquired=False),
        )

    assert repository.session_opened == 0
    assert vector_store.deleted_doc_ids == []
    assert vector_store.add_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("openai down"),
        OSError("elasticsearch down"),
    ],
)
async def test_vector_storage_model_or_elasticsearch_failure_rolls_back_and_cleans_doc_id(error):
    from app.modules.document import vector_storage

    repository = FakeRepository(batches=[[_segment(1)]])
    vector_store = FakeVectorStore(add_errors=[error])

    with pytest.raises(type(error)):
        await vector_storage.store_document_vectors(
            doc_id=42,
            document_repository=repository,
            vector_store=vector_store,
            lock=FakeLock(),
        )

    assert repository.session_obj.commits == 0
    assert repository.session_obj.rollbacks == 1
    assert vector_store.deleted_ids == []
    assert vector_store.deleted_doc_ids == [42, 42]


@pytest.mark.asyncio
async def test_vector_storage_returned_id_mismatch_cleans_returned_ids_and_doc_id():
    from app.modules.document import vector_storage
    from app.modules.document.vector_store import VectorStoreIdCountMismatch

    repository = FakeRepository(batches=[[_segment(1), _segment(2)]])
    vector_store = FakeVectorStore(
        add_errors=[VectorStoreIdCountMismatch(returned_ids=["orphan-id"])]
    )

    with pytest.raises(VectorStoreIdCountMismatch):
        await vector_storage.store_document_vectors(
            doc_id=42,
            document_repository=repository,
            vector_store=vector_store,
            lock=FakeLock(),
        )

    assert repository.session_obj.rollbacks == 1
    assert vector_store.deleted_ids == [["orphan-id"]]
    assert vector_store.deleted_doc_ids == [42, 42]


@pytest.mark.asyncio
async def test_vector_storage_db_update_failure_rolls_back_and_cleans_vectors():
    from app.modules.document import vector_storage
    from app.modules.document.errors import DocumentStateConflict

    repository = FakeRepository(
        batches=[[_segment(1), _segment(2)]],
        mark_error=DocumentStateConflict(),
    )
    vector_store = FakeVectorStore(id_batches=[["es-1", "es-2"]])

    with pytest.raises(DocumentStateConflict):
        await vector_storage.store_document_vectors(
            doc_id=42,
            document_repository=repository,
            vector_store=vector_store,
            lock=FakeLock(),
        )

    assert repository.session_obj.rollbacks == 1
    assert vector_store.deleted_ids == [["es-1", "es-2"]]
    assert vector_store.deleted_doc_ids == [42, 42]


@pytest.mark.asyncio
async def test_vector_storage_double_check_failure_rolls_back_and_cleans_vectors():
    from app.modules.document import vector_storage

    repository = FakeRepository(
        batches=[[_segment(1)], []],
        remaining_count=1,
    )
    vector_store = FakeVectorStore(id_batches=[["es-1"]])

    with pytest.raises(vector_storage.VectorStorageIncomplete):
        await vector_storage.store_document_vectors(
            doc_id=42,
            document_repository=repository,
            vector_store=vector_store,
            lock=FakeLock(),
        )

    assert repository.session_obj.rollbacks == 1
    assert repository.complete_calls == []
    assert vector_store.deleted_ids == [["es-1"]]
    assert vector_store.deleted_doc_ids == [42, 42]
