from types import SimpleNamespace


def test_rag_studio_binds_model_callback_and_compiles(
    monkeypatch,
):
    from app.entrypoints import rag_studio as studio

    settings = SimpleNamespace(openai_model="gpt-test")
    handler = object()
    resources = SimpleNamespace(handler=handler)
    assembled_model = object()
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
        return assembled_model

    monkeypatch.setattr(studio, "create_chat_model", fake_create_chat_model)
    monkeypatch.setattr(
        studio,
        "build_rag_graph",
        lambda **kwargs: calls.append(("builder", kwargs)) or FakeBuilder(),
    )

    assert studio.create_rag_studio_graph() is compiled
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
        ("builder", {"model": assembled_model}),
        ("compile", {}),
    ]


def test_rag_studio_runs_without_langfuse(monkeypatch):
    from app.entrypoints import rag_studio as studio

    settings = SimpleNamespace(openai_model="gpt-test")
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
        "build_rag_graph",
        lambda **kwargs: SimpleNamespace(compile=lambda: object()),
    )

    studio.create_rag_studio_graph()

    assert callbacks_seen == [None]
