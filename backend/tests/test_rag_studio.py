def test_rag_studio_reuses_shared_runtime_assembly(monkeypatch):
    from app.entrypoints import rag_studio as studio

    settings = object()
    compiled = object()
    calls = []
    monkeypatch.setattr(
        studio,
        "create_settings",
        lambda: calls.append("settings") or settings,
    )
    monkeypatch.setattr(
        studio,
        "validate_chat_startup_settings",
        lambda value: calls.append(("validate", value)) or value,
    )
    monkeypatch.setattr(
        studio,
        "create_compiled_rag_graph",
        lambda value: calls.append(("graph", value)) or compiled,
    )

    assert studio.create_rag_studio_graph() is compiled
    assert calls == [
        "settings",
        ("validate", settings),
        ("graph", settings),
    ]
