def test_rag_mcp_entrypoint_assembles_fixed_streamable_http_server(
    monkeypatch,
):
    from app.entrypoints import rag_mcp

    settings = object()
    graph = object()
    server = object()
    seen = []
    monkeypatch.setattr(
        rag_mcp,
        "create_settings",
        lambda: seen.append("settings") or settings,
    )
    monkeypatch.setattr(
        rag_mcp,
        "validate_chat_startup_settings",
        lambda value: seen.append(("validate", value)) or value,
    )
    monkeypatch.setattr(
        rag_mcp,
        "create_compiled_rag_graph",
        lambda value: seen.append(("graph", value)) or graph,
    )
    monkeypatch.setattr(
        rag_mcp,
        "RetrieveEvidenceService",
        lambda value: seen.append(("service", value)) or "service",
    )
    monkeypatch.setattr(
        rag_mcp,
        "create_rag_mcp_server",
        lambda value: seen.append(("server", value)) or server,
    )

    assert rag_mcp.create_server() is server
    assert seen == [
        "settings",
        ("validate", settings),
        ("graph", settings),
        ("service", graph),
        ("server", "service"),
    ]


def test_rag_mcp_main_runs_streamable_http(monkeypatch):
    from app.entrypoints import rag_mcp

    calls = []

    class FakeServer:
        def run(self, *, transport):
            calls.append(transport)

    monkeypatch.setattr(rag_mcp, "create_server", FakeServer)

    rag_mcp.main()

    assert calls == ["streamable-http"]
