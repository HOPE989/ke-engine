from uuid import uuid4

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


def test_chat_completion_lock_uses_conversation_key_expiry_and_auto_renewal(monkeypatch):
    from app.infrastructure import redis as redis_infrastructure

    captured = {}

    class FakeRedisLock:
        def __init__(self, redis_client, *, name, expire, auto_renewal):
            captured.update(
                redis_client=redis_client,
                name=name,
                expire=expire,
                auto_renewal=auto_renewal,
            )

    redis_client = object()
    monkeypatch.setattr(redis_infrastructure.redis_lock, "Lock", FakeRedisLock)

    lock = redis_infrastructure.chat_completion_lock(
        redis_client=redis_client,
        conversation_id=42,
        expire_seconds=120,
    )

    assert isinstance(lock, FakeRedisLock)
    assert captured == {
        "redis_client": redis_client,
        "name": "chat:conversation:42:completion",
        "expire": 120,
        "auto_renewal": True,
    }


@pytest.mark.asyncio
async def test_acquire_completion_lock_returns_owned_nonblocking_lock():
    from app.domains.chat.services.completion_lock import acquire_completion_lock

    lock = FakeLock(acquired=True)

    owned = await acquire_completion_lock(lock)

    assert owned is lock
    assert lock.acquire_calls == [{"blocking": False}]


@pytest.mark.asyncio
async def test_acquire_completion_lock_rejects_busy_conversation():
    from app.domains.chat.services.completion_lock import (
        ConversationBusy,
        acquire_completion_lock,
    )

    lock = FakeLock(acquired=False)

    with pytest.raises(ConversationBusy):
        await acquire_completion_lock(lock)

    assert lock.acquire_calls == [{"blocking": False}]
    assert lock.releases == 0


@pytest.mark.asyncio
async def test_acquire_completion_lock_maps_redis_failure():
    from app.domains.chat.services.completion_lock import (
        ConversationLockUnavailable,
        acquire_completion_lock,
    )

    lock = FakeLock(acquire_error=OSError("redis down"))

    with pytest.raises(ConversationLockUnavailable):
        await acquire_completion_lock(lock)

    assert lock.acquire_calls == [{"blocking": False}]
    assert lock.releases == 0


@pytest.mark.asyncio
async def test_release_completion_lock_releases_once_and_suppresses_redis_failure():
    from app.domains.chat.services.completion_lock import release_completion_lock

    successful = FakeLock()
    failing = FakeLock(release_error=OSError("redis down"))

    await release_completion_lock(successful)
    await release_completion_lock(failing)

    assert successful.releases == 1
    assert failing.releases == 1


def test_chat_completion_lock_expiry_is_positive_startup_configuration():
    from app.core import config

    settings = config.create_settings()

    assert settings.chat_completion_lock_expire_seconds == 120
    assert "chat_completion_lock_expire_seconds" in config.STARTUP_ONLY_SETTINGS
    description = config.Settings.model_fields[
        "chat_completion_lock_expire_seconds"
    ].description
    assert description is not None
    assert description.startswith("startup-only:")


@pytest.mark.integration
def test_real_redis_excludes_same_conversation_and_isolates_different_conversations():
    from app.core.config import create_settings
    from app.infrastructure.redis import chat_completion_lock, create_redis_client

    settings = create_settings()
    redis_client = create_redis_client(settings.redis_url)
    first_conversation_id = uuid4().int
    second_conversation_id = uuid4().int
    first = chat_completion_lock(
        redis_client=redis_client,
        conversation_id=first_conversation_id,
        expire_seconds=settings.chat_completion_lock_expire_seconds,
    )
    contender = chat_completion_lock(
        redis_client=redis_client,
        conversation_id=first_conversation_id,
        expire_seconds=settings.chat_completion_lock_expire_seconds,
    )
    independent = chat_completion_lock(
        redis_client=redis_client,
        conversation_id=second_conversation_id,
        expire_seconds=settings.chat_completion_lock_expire_seconds,
    )

    first_acquired = False
    contender_acquired = False
    independent_acquired = False
    try:
        first_acquired = first.acquire(blocking=False)
        assert first_acquired is True
        assert contender.acquire(blocking=False) is False

        independent_acquired = independent.acquire(blocking=False)
        assert independent_acquired is True

        first.release()
        first_acquired = False
        contender_acquired = contender.acquire(blocking=False)
        assert contender_acquired is True
    finally:
        if contender_acquired:
            contender.release()
        if first_acquired:
            first.release()
        if independent_acquired:
            independent.release()
        redis_client.close()
