from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI


def _settings():
    return SimpleNamespace(
        app_name="ke-engine",
        app_version="0.1.0",
        debug=False,
        api_v1_prefix="/api/v1",
        database_url="postgresql+asyncpg://user:pass@db.example/app",
        redis_url="redis://redis.example:6379/0",
        chat_completion_lock_expire_seconds=120,
        openai_model="gpt-test",
        snowflake_worker_id=7,
    )


@pytest.mark.asyncio
async def test_chat_lifespan_compiles_after_model_and_saver_and_closes_in_order(
    monkeypatch,
):
    from app.services.chat_api import deps

    calls = []
    session_factory = object()
    chat_model = object()
    title_model = object()
    saver = object()
    graph = object()
    class FakeRedis:
        def close(self):
            calls.append("redis_close")

    redis_client = FakeRedis()

    async def fake_initialize_database_deps(*, stack, settings):
        calls.append("database_open")
        stack.push_cleanup(lambda: calls.append("database_close"))
        return session_factory

    def fake_create_chat_model(settings, *, model):
        calls.append(f"model_create:{model}")
        if model == "gpt-test":
            return chat_model
        if model == "qwen3.6-flash":
            return title_model
        raise AssertionError(f"unexpected model: {model}")

    @asynccontextmanager
    async def fake_postgres_checkpointer(database_url):
        calls.append("saver_open")
        try:
            yield saver
        finally:
            calls.append("saver_close")

    class FakeBuilder:
        def compile(self, *, checkpointer):
            assert calls == [
                "database_open",
                "model_create:gpt-test",
                "model_create:qwen3.6-flash",
                "saver_open",
                "redis_open",
                "build_graph",
            ]
            assert checkpointer is saver
            calls.append("compile_graph")
            return graph

    class FakeRegistry:
        async def shutdown(self):
            calls.append("registry_shutdown")

    registry = FakeRegistry()

    def fake_create_redis_client(redis_url):
        assert redis_url == "redis://redis.example:6379/0"
        calls.append("redis_open")
        return redis_client

    monkeypatch.setattr(deps, "initialize_database_deps", fake_initialize_database_deps)
    monkeypatch.setattr(deps, "create_chat_model", fake_create_chat_model)
    monkeypatch.setattr(deps, "postgres_checkpointer", fake_postgres_checkpointer)
    monkeypatch.setattr(
        deps,
        "create_redis_client",
        fake_create_redis_client,
        raising=False,
    )
    monkeypatch.setattr(
        deps,
        "build_chat_graph",
        lambda: calls.append("build_graph") or FakeBuilder(),
    )
    monkeypatch.setattr(
        deps,
        "create_producer_registry",
        lambda: calls.append("registry_create") or registry,
    )

    application = FastAPI()
    async with deps.application_lifespan_resources(application, _settings()):
        assert calls == [
            "database_open",
            "model_create:gpt-test",
            "model_create:qwen3.6-flash",
            "saver_open",
            "redis_open",
            "build_graph",
            "compile_graph",
            "registry_create",
        ]
        assert application.state.chat_deps == deps.ChatApiDeps(
            session_factory=session_factory,
            id_generator=application.state.chat_deps.id_generator,
            graph=graph,
            model=chat_model,
            title_model=title_model,
            redis_client=redis_client,
            completion_lock_expire_seconds=120,
            producer_registry=registry,
        )

    assert calls[-4:] == [
        "registry_shutdown",
        "redis_close",
        "saver_close",
        "database_close",
    ]
    assert not hasattr(application.state, "chat_deps")


@pytest.mark.asyncio
async def test_chat_lifespan_model_failure_aborts_startup_before_saver(monkeypatch):
    from app.services.chat_api import deps

    calls = []

    async def fake_initialize_database_deps(*, stack, settings):
        calls.append("database_open")
        stack.push_cleanup(lambda: calls.append("database_close"))
        return object()

    def fail_model(settings, *, model):
        calls.append("model_failed")
        raise RuntimeError("model unavailable")

    def unexpected_saver(database_url):
        raise AssertionError("saver must not start after model failure")

    monkeypatch.setattr(deps, "initialize_database_deps", fake_initialize_database_deps)
    monkeypatch.setattr(deps, "create_chat_model", fail_model)
    monkeypatch.setattr(deps, "postgres_checkpointer", unexpected_saver)

    with pytest.raises(RuntimeError, match="model unavailable"):
        async with deps.application_lifespan_resources(FastAPI(), _settings()):
            pass

    assert calls == ["database_open", "model_failed", "database_close"]


@pytest.mark.asyncio
async def test_chat_lifespan_saver_failure_aborts_without_memory_fallback(monkeypatch):
    from app.services.chat_api import deps

    calls = []

    async def fake_initialize_database_deps(*, stack, settings):
        calls.append("database_open")
        stack.push_cleanup(lambda: calls.append("database_close"))
        return object()

    @asynccontextmanager
    async def fail_saver(database_url):
        calls.append("saver_failed")
        raise RuntimeError("saver unavailable")
        yield

    monkeypatch.setattr(deps, "initialize_database_deps", fake_initialize_database_deps)
    monkeypatch.setattr(deps, "create_chat_model", lambda settings, *, model: object())
    monkeypatch.setattr(deps, "postgres_checkpointer", fail_saver)
    monkeypatch.setattr(
        deps,
        "build_chat_graph",
        lambda: (_ for _ in ()).throw(AssertionError("graph must not compile")),
    )

    with pytest.raises(RuntimeError, match="saver unavailable"):
        async with deps.application_lifespan_resources(FastAPI(), _settings()):
            pass

    assert calls == ["database_open", "saver_failed", "database_close"]
