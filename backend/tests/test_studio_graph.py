import json
from pathlib import Path
from types import SimpleNamespace


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_studio_graph_binds_one_model_to_existing_builder(monkeypatch):
    from app.entrypoints import studio_graph as studio

    settings = SimpleNamespace(openai_model="gpt-test")
    handler = object()
    resources = SimpleNamespace(handler=handler)
    bound_model = object()
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
        lambda value: calls.append(("langfuse", value)) or resources,
    )

    def fake_create_chat_model(value, *, model: str, callbacks=None):
        calls.append(
            (
                "model",
                {"settings": value, "model": model, "callbacks": callbacks},
            )
        )
        return bound_model

    monkeypatch.setattr(studio, "create_chat_model", fake_create_chat_model)
    monkeypatch.setattr(
        studio,
        "build_chat_graph",
        lambda **kwargs: calls.append(("builder", kwargs)) or FakeBuilder(),
    )

    assert studio.create_studio_graph() is compiled
    assert calls == [
        ("validate", settings),
        ("langfuse", settings),
        (
            "model",
            {
                "settings": settings,
                "model": "gpt-test",
                "callbacks": [handler],
            },
        ),
        ("builder", {"bound_model": bound_model}),
        ("compile", {}),
    ]


def test_studio_graph_is_fail_open_when_langfuse_is_unavailable(monkeypatch):
    from app.entrypoints import studio_graph as studio

    settings = SimpleNamespace(openai_model="gpt-test")
    callbacks_seen = []
    monkeypatch.setattr(studio, "create_settings", lambda: settings)
    monkeypatch.setattr(studio, "validate_chat_startup_settings", lambda value: value)
    monkeypatch.setattr(studio, "create_langfuse_resources", lambda value: None)
    monkeypatch.setattr(
        studio,
        "create_chat_model",
        lambda value, *, model, callbacks=None: callbacks_seen.append(callbacks)
        or object(),
    )
    monkeypatch.setattr(
        studio,
        "build_chat_graph",
        lambda **kwargs: SimpleNamespace(compile=lambda: object()),
    )

    studio.create_studio_graph()

    assert callbacks_seen == [None]


def test_chat_model_factory_passes_optional_callbacks(monkeypatch):
    from app.infrastructure import llm

    captured = {}
    callbacks = [object()]
    monkeypatch.setattr(
        llm,
        "ChatOpenAI",
        lambda **kwargs: captured.update(kwargs) or object(),
    )

    llm.create_chat_model(
        SimpleNamespace(openai_api_key="key", openai_base_url="http://model"),
        model="gpt-test",
        callbacks=callbacks,
    )

    assert captured["callbacks"] is callbacks


def test_langgraph_json_exports_thin_chat_and_rag_studio_graphs():
    config = json.loads(
        (BACKEND_ROOT / "langgraph.json").read_text(encoding="utf-8")
    )

    assert config == {
        "dependencies": ["."],
        "graphs": {
            "chat": "./app/entrypoints/studio_graph.py:create_studio_graph",
            "rag": (
                "./app/entrypoints/rag_studio.py:"
                "create_rag_studio_graph"
            ),
        },
        "env": ".env",
    }


def test_studio_adapter_does_not_import_fastapi_business_resources():
    source = (
        BACKEND_ROOT / "app" / "entrypoints" / "studio_graph.py"
    ).read_text(encoding="utf-8")

    forbidden = [
        "app.services.chat_api",
        "initialize_database_deps",
        "postgres_checkpointer",
        "create_redis_client",
        "CompletionProducerRegistry",
        "TITLE_MODEL",
    ]
    assert [name for name in forbidden if name in source] == []
