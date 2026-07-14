import pytest


class FakeLock:
    def __init__(self, *, acquired=True, acquire_error=None, release_error=None):
        self.acquired = acquired
        self.acquire_error = acquire_error
        self.release_error = release_error
        self.acquire_calls = []
        self.releases = 0

    def acquire(self, *, blocking):
        self.acquire_calls.append({"blocking": blocking})
        if self.acquire_error is not None:
            raise self.acquire_error
        return self.acquired

    def release(self):
        self.releases += 1
        if self.release_error is not None:
            raise self.release_error


def test_document_chunking_lock_factory_uses_document_chunk_key(monkeypatch):
    from app.infrastructure import redis as redis_lock

    captured = {}

    class FakeRedisLock:
        def __init__(self, redis_client, *, name, expire, auto_renewal):
            captured["redis_client"] = redis_client
            captured["name"] = name
            captured["expire"] = expire
            captured["auto_renewal"] = auto_renewal

    redis_client = object()
    monkeypatch.setattr(redis_lock.redis_lock, "Lock", FakeRedisLock)

    lock = redis_lock.document_chunking_lock(
        redis_client=redis_client,
        doc_id=42,
        expire_seconds=120,
    )

    assert isinstance(lock, FakeRedisLock)
    assert captured == {
        "redis_client": redis_client,
        "name": "document:42:chunk",
        "expire": 120,
        "auto_renewal": True,
    }


@pytest.mark.asyncio
async def test_document_chunk_lock_helper_acquires_and_releases_lock():
    from app.domains.document.components.splitters import run_with_document_chunk_lock

    calls = []

    async def operation():
        calls.append("operation")
        return "chunked"

    lock = FakeLock(acquired=True)

    result = await run_with_document_chunk_lock(lock=lock, operation=operation)

    assert result == "chunked"
    assert lock.acquire_calls == [{"blocking": False}]
    assert lock.releases == 1
    assert calls == ["operation"]


@pytest.mark.asyncio
async def test_document_chunk_lock_helper_rejects_busy_lock_without_operation():
    from app.domains.document.components.splitters import run_with_document_chunk_lock
    from app.domains.document.shared.errors import DocumentStateConflict

    calls = []

    async def operation():
        calls.append("operation")

    lock = FakeLock(acquired=False)

    with pytest.raises(DocumentStateConflict):
        await run_with_document_chunk_lock(lock=lock, operation=operation)

    assert lock.acquire_calls == [{"blocking": False}]
    assert lock.releases == 0
    assert calls == []


@pytest.mark.asyncio
async def test_document_chunk_lock_helper_maps_lock_infrastructure_failure():
    from app.domains.document.components.splitters import run_with_document_chunk_lock
    from app.domains.document.shared.errors import ChunkLockUnavailable

    async def operation():
        raise AssertionError("operation must not run when lock infrastructure fails")

    lock = FakeLock(acquire_error=OSError("redis down"))

    with pytest.raises(ChunkLockUnavailable):
        await run_with_document_chunk_lock(lock=lock, operation=operation)

    assert lock.acquire_calls == [{"blocking": False}]
    assert lock.releases == 0


@pytest.mark.asyncio
async def test_document_chunk_lock_helper_ignores_release_failure_after_success():
    from app.domains.document.components.splitters import run_with_document_chunk_lock

    async def operation():
        return "chunked"

    lock = FakeLock(release_error=OSError("redis release failed"))

    result = await run_with_document_chunk_lock(lock=lock, operation=operation)

    assert result == "chunked"
    assert lock.acquire_calls == [{"blocking": False}]
    assert lock.releases == 1


@pytest.mark.asyncio
async def test_document_chunk_lock_helper_preserves_operation_failure_when_release_fails():
    from app.domains.document.components.splitters import run_with_document_chunk_lock

    operation_error = RuntimeError("markdown failed")

    async def operation():
        raise operation_error

    lock = FakeLock(release_error=OSError("redis release failed"))

    with pytest.raises(RuntimeError) as exc_info:
        await run_with_document_chunk_lock(lock=lock, operation=operation)

    assert exc_info.value is operation_error
    assert lock.acquire_calls == [{"blocking": False}]
    assert lock.releases == 1
