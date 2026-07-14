import pytest


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        (
            "postgresql+asyncpg://user:pass@db.example:5432/app",
            "postgresql://user:pass@db.example:5432/app",
        ),
        (
            "postgresql+asyncpg://user%40tenant:p%40ss%2Fword@db.example/app"
            "?sslmode=require&application_name=chat",
            "postgresql://user%40tenant:p%40ss%2Fword@db.example/app"
            "?application_name=chat&sslmode=require",
        ),
        (
            "postgresql://user:pass@db.example/app?connect_timeout=5",
            "postgresql://user:pass@db.example/app?connect_timeout=5",
        ),
    ],
)
def test_to_psycopg_dsn_preserves_credentials_and_query(database_url, expected):
    from app.infrastructure.langgraph import to_psycopg_dsn

    assert to_psycopg_dsn(database_url) == expected


@pytest.mark.parametrize("database_url", ["mysql://user:pass@db/app", "sqlite:///app.db"])
def test_to_psycopg_dsn_rejects_non_postgresql_urls(database_url):
    from app.infrastructure.langgraph import to_psycopg_dsn

    with pytest.raises(ValueError, match="PostgreSQL"):
        to_psycopg_dsn(database_url)


class FakePool:
    def __init__(self, calls):
        self.calls = calls

    async def open(self):
        self.calls.append(("pool_open", self))

    async def close(self):
        self.calls.append(("pool_close", self))


class FakeSaver:
    def __init__(self, pool, calls):
        self.pool = pool
        self.calls = calls

    async def setup(self):
        self.calls.append(("saver_setup", self.pool))


@pytest.mark.asyncio
async def test_postgres_checkpointer_uses_dedicated_pool_and_sets_up_once(monkeypatch):
    from app.infrastructure import langgraph
    from app.infrastructure.db import session

    calls = []
    checkpoint_pool = FakePool(calls)
    business_engine = object()
    monkeypatch.setattr(session, "get_engine", lambda: business_engine)
    monkeypatch.setattr(
        langgraph,
        "_create_pool",
        lambda dsn: calls.append(("create_pool", dsn)) or checkpoint_pool,
    )
    monkeypatch.setattr(
        langgraph,
        "AsyncPostgresSaver",
        lambda pool: FakeSaver(pool, calls),
    )

    async with langgraph.postgres_checkpointer(
        "postgresql+asyncpg://user:pass@db.example/app"
    ) as saver:
        assert saver.pool is checkpoint_pool
        assert saver.pool is not business_engine
        calls.append(("yield", saver.pool))

    assert calls == [
        ("create_pool", "postgresql://user:pass@db.example/app"),
        ("pool_open", checkpoint_pool),
        ("saver_setup", checkpoint_pool),
        ("yield", checkpoint_pool),
        ("pool_close", checkpoint_pool),
    ]


@pytest.mark.asyncio
async def test_postgres_checkpointer_closes_pool_when_body_raises(monkeypatch):
    from app.infrastructure import langgraph

    calls = []
    pool = FakePool(calls)
    monkeypatch.setattr(langgraph, "_create_pool", lambda dsn: pool)
    monkeypatch.setattr(
        langgraph,
        "AsyncPostgresSaver",
        lambda created_pool: FakeSaver(created_pool, calls),
    )

    with pytest.raises(RuntimeError, match="body failed"):
        async with langgraph.postgres_checkpointer(
            "postgresql+asyncpg://user:pass@db.example/app"
        ):
            raise RuntimeError("body failed")

    assert calls == [
        ("pool_open", pool),
        ("saver_setup", pool),
        ("pool_close", pool),
    ]
