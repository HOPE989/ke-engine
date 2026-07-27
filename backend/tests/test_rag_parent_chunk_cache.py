import pytest


class FakeRepository:
    def __init__(self):
        self.calls = []

    async def get_parent_texts(self, references):
        self.calls.append(tuple(references))
        return {
            ("1001", "parent-db"): "数据库父分段",
        }


class FakePipeline:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.commands = []

    def set(self, key, value, *, ex):
        self.commands.append((key, value, ex))
        return self

    def execute(self):
        self.redis_client.pipeline_calls.append(tuple(self.commands))
        for key, value, _ in self.commands:
            self.redis_client.values[key] = value
        return [True] * len(self.commands)


class FakeRedis:
    def __init__(self):
        self.values = {
            "rag:parent-chunk:1001:parent-redis": "Redis父分段".encode(),
            "rag:parent-chunk:1001:parent-negative": b"\x00",
        }
        self.mget_calls = []
        self.pipeline_calls = []

    def mget(self, keys):
        self.mget_calls.append(tuple(keys))
        return [self.values.get(key) for key in keys]

    def pipeline(self, *, transaction):
        assert transaction is False
        return FakePipeline(self)


@pytest.mark.asyncio
async def test_parent_chunk_loader_uses_local_redis_and_postgres_caches():
    from app.infrastructure.parent_chunks import CachedParentChunkLoader

    repository = FakeRepository()
    redis_client = FakeRedis()
    loader = CachedParentChunkLoader(
        repository=repository,
        redis_client=redis_client,
        cache_ttl_seconds=30,
        missing_cache_ttl_seconds=5,
    )
    references = [
        ("1001", "parent-redis"),
        ("1001", "parent-redis"),
        ("1001", "parent-db"),
        ("1001", "parent-negative"),
        ("1001", "parent-missing"),
    ]

    first = await loader.load(references)
    second = await loader.load(references)

    assert first == second == {
        ("1001", "parent-redis"): "Redis父分段",
        ("1001", "parent-db"): "数据库父分段",
    }
    expected_keys = (
        "rag:parent-chunk:1001:parent-redis",
        "rag:parent-chunk:1001:parent-db",
        "rag:parent-chunk:1001:parent-negative",
        "rag:parent-chunk:1001:parent-missing",
    )
    assert redis_client.mget_calls == [expected_keys, expected_keys]
    assert repository.calls == [
        (
            ("1001", "parent-db"),
            ("1001", "parent-missing"),
        )
    ]
    assert redis_client.pipeline_calls == [
        (
            (
                "rag:parent-chunk:1001:parent-db",
                "数据库父分段",
                30,
            ),
            (
                "rag:parent-chunk:1001:parent-missing",
                "\x00",
                5,
            ),
        )
    ]


@pytest.mark.asyncio
async def test_parent_chunk_loader_falls_back_when_redis_is_unavailable():
    from app.infrastructure.parent_chunks import CachedParentChunkLoader

    class UnavailableRedis:
        def mget(self, keys):
            del keys
            raise ConnectionError("redis unavailable")

        def pipeline(self, *, transaction):
            del transaction
            raise ConnectionError("redis unavailable")

    repository = FakeRepository()
    loader = CachedParentChunkLoader(
        repository=repository,
        redis_client=UnavailableRedis(),
    )

    result = await loader.load([("1001", "parent-db")])

    assert result == {
        ("1001", "parent-db"): "数据库父分段",
    }
    assert repository.calls == [(("1001", "parent-db"),)]
