from types import SimpleNamespace


def test_rag_studio_assembles_without_probing_elasticsearch_index(
    monkeypatch,
):
    from app.entrypoints import rag_studio as studio

    settings = SimpleNamespace(
        openai_model="gpt-test",
        elasticsearch_index="rag-documents",
        embedding_dimensions=1536,
    )
    handler = object()
    model = object()
    embedding_model = object()
    client = object()
    store = object()
    options = object()
    factory = object()
    parent_chunk_cache = object()
    compiled = object()
    calls = []

    class FakeBuilder:
        def compile(self):
            calls.append(("compile", {}))
            return compiled

    monkeypatch.setattr(studio, "create_settings", lambda: settings)
    monkeypatch.setattr(
        studio,
        "validate_chat_startup_settings",
        lambda value: calls.append(("validate", value)) or value,
    )
    monkeypatch.setattr(
        studio,
        "create_langfuse_resources",
        lambda value: SimpleNamespace(handler=handler),
    )
    def fake_create_chat_model(
        value,
        *,
        model: str,
        callbacks=None,
    ):
        calls.append(("model", callbacks))
        return globals_model

    globals_model = model
    monkeypatch.setattr(
        studio,
        "create_chat_model",
        fake_create_chat_model,
    )
    monkeypatch.setattr(
        studio,
        "create_embedding_model",
        lambda value: calls.append(("embedding", value))
        or embedding_model,
    )
    monkeypatch.setattr(
        studio,
        "create_elasticsearch_client",
        lambda value: calls.append(("client", value)) or client,
    )
    monkeypatch.setattr(
        studio,
        "DocumentRetrievalOptions",
        lambda: options,
    )
    monkeypatch.setattr(
        studio,
        "create_document_retrieval_store",
        lambda **kwargs: calls.append(("store", kwargs)) or store,
    )
    monkeypatch.setattr(
        studio,
        "create_parent_chunk_cache",
        lambda value: calls.append(("parent-cache", value))
        or parent_chunk_cache,
    )
    monkeypatch.setattr(
        studio,
        "DocumentHybridRetrieverFactory",
        lambda **kwargs: calls.append(("factory", kwargs)) or factory,
    )
    monkeypatch.setattr(
        studio,
        "build_rag_graph",
        lambda **kwargs: calls.append(("builder", kwargs))
        or FakeBuilder(),
    )

    result = studio.create_rag_studio_graph()

    assert result is compiled
    assert ("model", [handler]) in calls
    assert ("embedding", settings) in calls
    assert (
        "store",
        {
            "settings": settings,
            "embedding_model": embedding_model,
            "client": client,
        },
    ) in calls
    assert (
        "factory",
        {
            "client": client,
            "store": store,
            "index_name": "rag-documents",
            "options": options,
            "parent_chunk_cache": parent_chunk_cache,
        },
    ) in calls
    assert (
        "builder",
        {
            "model": model,
            "document_retriever_factory": factory,
            "retrieval_options": options,
        },
    ) in calls
    assert calls[-1] == ("compile", {})


def test_rag_studio_runs_without_langfuse(monkeypatch):
    from app.entrypoints import rag_studio as studio

    settings = SimpleNamespace(
        openai_model="gpt-test",
        elasticsearch_index="rag-documents",
        embedding_dimensions=1536,
    )
    callbacks_seen = []
    monkeypatch.setattr(studio, "create_settings", lambda: settings)
    monkeypatch.setattr(
        studio,
        "validate_chat_startup_settings",
        lambda value: value,
    )
    monkeypatch.setattr(
        studio,
        "create_langfuse_resources",
        lambda value: None,
    )
    monkeypatch.setattr(
        studio,
        "create_chat_model",
        lambda value, *, model, callbacks=None: callbacks_seen.append(
            callbacks
        )
        or object(),
    )
    monkeypatch.setattr(
        studio,
        "create_embedding_model",
        lambda value: object(),
    )
    monkeypatch.setattr(
        studio,
        "create_elasticsearch_client",
        lambda value: SimpleNamespace(indices=SimpleNamespace()),
    )
    monkeypatch.setattr(
        studio,
        "create_document_retrieval_store",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        studio,
        "create_parent_chunk_cache",
        lambda value: object(),
    )
    monkeypatch.setattr(
        studio,
        "build_rag_graph",
        lambda **kwargs: SimpleNamespace(compile=lambda: object()),
    )

    studio.create_rag_studio_graph()

    assert callbacks_seen == [None]


def test_parent_chunk_cache_disables_local_postgres_ssl_probe(
    monkeypatch,
):
    from app.entrypoints import rag_studio as studio

    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://user:pass@db/app",
        redis_url="redis://redis.example:6379/0",
    )
    engine = object()
    session_factory = object()
    repository = object()
    redis_client = object()
    captured = {}

    def fake_create_async_engine(database_url, **kwargs):
        captured["engine"] = (database_url, kwargs)
        return engine

    def fake_session_factory(**kwargs):
        captured["session"] = kwargs
        return session_factory

    def fake_repository(value):
        captured["repository"] = value
        return repository

    def fake_redis_client(value):
        captured["redis"] = value
        return redis_client

    monkeypatch.setattr(
        studio,
        "create_async_engine",
        fake_create_async_engine,
    )
    monkeypatch.setattr(
        studio,
        "async_sessionmaker",
        fake_session_factory,
    )
    monkeypatch.setattr(
        studio,
        "SegmentRepository",
        fake_repository,
    )
    monkeypatch.setattr(
        studio,
        "create_redis_client",
        fake_redis_client,
    )

    cache = studio.create_parent_chunk_cache(settings)

    assert captured["engine"] == (
        settings.database_url,
        {
            "pool_pre_ping": True,
            "connect_args": {"ssl": False},
        },
    )
    assert cache.repository is repository
    assert cache.redis_client is redis_client
