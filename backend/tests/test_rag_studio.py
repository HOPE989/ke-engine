from types import SimpleNamespace


def test_rag_studio_assembles_model_hybrid_store_and_registered_node(
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
        "ensure_vector_index",
        lambda value, **kwargs: calls.append(
            ("mapping", value, kwargs)
        ),
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
        "mapping",
        client,
        {
            "index_name": "rag-documents",
            "embedding_dimensions": 1536,
        },
    ) in calls
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
    monkeypatch.setattr(studio, "ensure_vector_index", lambda *a, **k: None)
    monkeypatch.setattr(
        studio,
        "create_document_retrieval_store",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        studio,
        "build_rag_graph",
        lambda **kwargs: SimpleNamespace(compile=lambda: object()),
    )

    studio.create_rag_studio_graph()

    assert callbacks_seen == [None]
