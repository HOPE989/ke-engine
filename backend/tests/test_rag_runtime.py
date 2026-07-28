from types import SimpleNamespace


def test_shared_rag_runtime_assembles_existing_resources(monkeypatch):
    from app.infrastructure import rag_runtime

    settings = SimpleNamespace(
        openai_model="gpt-test",
        openai_api_key="existing-key",
        openai_base_url="https://workspace.example/v1",
        elasticsearch_index="rag-documents",
    )
    resources = {
        name: object()
        for name in (
            "handler",
            "model",
            "embedding",
            "client",
            "store",
            "options",
            "http",
            "reranker",
            "cache",
            "factory",
            "compiled",
        )
    }
    resources["options"] = SimpleNamespace(timeout_seconds=10)
    calls = []

    class FakeBuilder:
        def compile(self):
            calls.append(("compile", {}))
            return resources["compiled"]

    monkeypatch.setattr(
        rag_runtime,
        "create_langfuse_resources",
        lambda value: SimpleNamespace(handler=resources["handler"]),
    )
    monkeypatch.setattr(
        rag_runtime,
        "create_chat_model",
        lambda value, *, model, callbacks=None: calls.append(
            ("model", value, model, callbacks)
        )
        or resources["model"],
    )
    monkeypatch.setattr(
        rag_runtime,
        "create_embedding_model",
        lambda value: resources["embedding"],
    )
    monkeypatch.setattr(
        rag_runtime,
        "create_elasticsearch_client",
        lambda value: resources["client"],
    )
    monkeypatch.setattr(
        rag_runtime,
        "DocumentRetrievalOptions",
        lambda: resources["options"],
    )
    monkeypatch.setattr(
        rag_runtime,
        "get_shared_rerank_http_client",
        lambda: resources["http"],
    )
    monkeypatch.setattr(
        rag_runtime,
        "BailianQwen3Reranker",
        lambda **kwargs: calls.append(("reranker", kwargs))
        or resources["reranker"],
    )
    monkeypatch.setattr(
        rag_runtime,
        "create_document_retrieval_store",
        lambda **kwargs: calls.append(("store", kwargs))
        or resources["store"],
    )
    monkeypatch.setattr(
        rag_runtime,
        "create_parent_chunk_cache",
        lambda value: resources["cache"],
    )
    monkeypatch.setattr(
        rag_runtime,
        "DocumentHybridRetrieverFactory",
        lambda **kwargs: calls.append(("factory", kwargs))
        or resources["factory"],
    )
    monkeypatch.setattr(
        rag_runtime,
        "build_rag_graph",
        lambda **kwargs: calls.append(("builder", kwargs)) or FakeBuilder(),
    )

    result = rag_runtime.create_compiled_rag_graph(settings)

    assert result is resources["compiled"]
    assert (
        "model",
        settings,
        "gpt-test",
        [resources["handler"]],
    ) in calls
    assert (
        "factory",
        {
            "client": resources["client"],
            "store": resources["store"],
            "index_name": "rag-documents",
            "options": resources["options"],
            "reranker": resources["reranker"],
            "parent_chunk_cache": resources["cache"],
        },
    ) in calls
    assert calls[-1] == ("compile", {})


def test_shared_rag_runtime_runs_without_langfuse(monkeypatch):
    from app.infrastructure import rag_runtime

    settings = SimpleNamespace(
        openai_model="gpt-test",
        openai_api_key="key",
        openai_base_url="https://workspace.example/v1",
        elasticsearch_index="rag-documents",
    )
    callbacks_seen = []
    monkeypatch.setattr(
        rag_runtime, "create_langfuse_resources", lambda value: None
    )
    monkeypatch.setattr(
        rag_runtime,
        "create_chat_model",
        lambda value, *, model, callbacks=None: callbacks_seen.append(
            callbacks
        )
        or object(),
    )
    monkeypatch.setattr(
        rag_runtime, "create_embedding_model", lambda value: object()
    )
    monkeypatch.setattr(
        rag_runtime, "create_elasticsearch_client", lambda value: object()
    )
    monkeypatch.setattr(
        rag_runtime,
        "create_document_retrieval_store",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        rag_runtime, "create_parent_chunk_cache", lambda value: object()
    )
    monkeypatch.setattr(
        rag_runtime,
        "get_shared_rerank_http_client",
        lambda: object(),
    )
    monkeypatch.setattr(
        rag_runtime, "BailianQwen3Reranker", lambda **kwargs: object()
    )
    monkeypatch.setattr(
        rag_runtime,
        "DocumentHybridRetrieverFactory",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        rag_runtime,
        "build_rag_graph",
        lambda **kwargs: SimpleNamespace(compile=lambda: object()),
    )

    rag_runtime.create_compiled_rag_graph(settings)

    assert callbacks_seen == [None]


def test_parent_chunk_cache_disables_local_postgres_ssl_probe(monkeypatch):
    from app.infrastructure import rag_runtime

    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://user:pass@db/app",
        redis_url="redis://redis.example:6379/0",
    )
    captured = {}
    engine = object()
    session_factory = object()
    repository = object()
    redis_client = object()
    monkeypatch.setattr(
        rag_runtime,
        "create_async_engine",
        lambda database_url, **kwargs: captured.setdefault(
            "engine", (database_url, kwargs)
        )
        and engine,
    )
    monkeypatch.setattr(
        rag_runtime,
        "async_sessionmaker",
        lambda **kwargs: captured.setdefault("session", kwargs)
        and session_factory,
    )
    monkeypatch.setattr(
        rag_runtime,
        "SegmentRepository",
        lambda value: captured.setdefault("repository", value)
        and repository,
    )
    monkeypatch.setattr(
        rag_runtime,
        "create_redis_client",
        lambda value: captured.setdefault("redis", value)
        and redis_client,
    )

    cache = rag_runtime.create_parent_chunk_cache(settings)

    assert captured["engine"] == (
        settings.database_url,
        {
            "pool_pre_ping": True,
            "connect_args": {"ssl": False},
        },
    )
    assert cache.repository is repository
    assert cache.redis_client is redis_client
