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
    def __init__(self, pool, calls, serde):
        self.pool = pool
        self.calls = calls
        self.serde = serde

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
        lambda pool, *, serde: FakeSaver(pool, calls, serde),
    )

    async with langgraph.postgres_checkpointer(
        "postgresql+asyncpg://user:pass@db.example/app"
    ) as saver:
        assert saver.pool is checkpoint_pool
        assert saver.pool is not business_engine
        assert isinstance(saver.serde, langgraph.JsonPlusSerializer)
        calls.append(("yield", saver.pool))

    assert calls == [
        ("create_pool", "postgresql://user:pass@db.example/app"),
        ("pool_open", checkpoint_pool),
        ("saver_setup", checkpoint_pool),
        ("yield", checkpoint_pool),
        ("pool_close", checkpoint_pool),
    ]


@pytest.mark.asyncio
async def test_postgres_checkpointer_configures_exact_business_understanding_allowlist(
    monkeypatch,
):
    from app.infrastructure import langgraph

    calls = []
    pool = FakePool(calls)
    captured_kwargs = {}
    serializer = object()

    def create_serializer(**kwargs):
        captured_kwargs.update(kwargs)
        return serializer

    monkeypatch.setattr(langgraph, "_create_pool", lambda dsn: pool)
    monkeypatch.setattr(langgraph, "JsonPlusSerializer", create_serializer)
    monkeypatch.setattr(
        langgraph,
        "AsyncPostgresSaver",
        lambda created_pool, *, serde: FakeSaver(created_pool, calls, serde),
    )

    async with langgraph.postgres_checkpointer(
        "postgresql+asyncpg://user:pass@db.example/app"
    ) as saver:
        assert saver.serde is serializer

    assert captured_kwargs == {
        "allowed_msgpack_modules": (
            (
                "app.domains.chat.graph.business_understanding.models",
                "BusinessRoute",
            ),
            (
                "app.domains.chat.graph.business_understanding.models",
                "BusinessIntent",
            ),
            (
                "app.domains.chat.graph.business_understanding.models",
                "BusinessUnderstandingResult",
            ),
        )
    }
    assert captured_kwargs["allowed_msgpack_modules"] is not True


@pytest.mark.asyncio
async def test_postgres_checkpointer_serializer_strictly_round_trips_business_state(
    monkeypatch,
):
    from langchain_core.messages import HumanMessage

    from app.domains.chat.graph.business_understanding.models import (
        BusinessEntities,
        BusinessIntent,
        BusinessRoute,
        BusinessUnderstandingResult,
    )
    from app.infrastructure import langgraph

    calls = []
    pool = FakePool(calls)
    monkeypatch.setattr(langgraph, "_create_pool", lambda dsn: pool)
    monkeypatch.setattr(
        langgraph,
        "AsyncPostgresSaver",
        lambda created_pool, *, serde: FakeSaver(created_pool, calls, serde),
    )
    result = BusinessUnderstandingResult(
        reasoning="用户明确查询运输计划",
        route=BusinessRoute.BUSINESS,
        intent=BusinessIntent.BUSINESS_DATA_QUERY,
        entities=BusinessEntities(
            operation_plan_no="PLAN-001",
            train_no="TRAIN-002",
            document_type="运单",
            document_no="DOC-003",
        ),
    )
    payload = {
        "business_understanding": result,
        "messages": [HumanMessage(content="查询 PLAN-001 对应的运单")],
    }

    async with langgraph.postgres_checkpointer(
        "postgresql+asyncpg://user:pass@db.example/app"
    ) as saver:
        restored = saver.serde.loads_typed(saver.serde.dumps_typed(payload))

    restored_result = restored["business_understanding"]
    assert type(restored_result) is BusinessUnderstandingResult
    assert type(restored_result.entities) is BusinessEntities
    assert type(restored_result.route) is BusinessRoute
    assert restored_result.route is BusinessRoute.BUSINESS
    assert type(restored_result.intent) is BusinessIntent
    assert restored_result.intent is BusinessIntent.BUSINESS_DATA_QUERY
    assert restored_result == result
    assert len(restored["messages"]) == 1
    assert type(restored["messages"][0]) is HumanMessage
    assert restored["messages"][0] == payload["messages"][0]


@pytest.mark.asyncio
async def test_postgres_checkpointer_closes_pool_when_body_raises(monkeypatch):
    from app.infrastructure import langgraph

    calls = []
    pool = FakePool(calls)
    monkeypatch.setattr(langgraph, "_create_pool", lambda dsn: pool)
    monkeypatch.setattr(
        langgraph,
        "AsyncPostgresSaver",
        lambda created_pool, *, serde: FakeSaver(created_pool, calls, serde),
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
