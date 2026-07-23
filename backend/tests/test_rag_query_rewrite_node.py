import asyncio
import importlib
import sys

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from pydantic import ValidationError

from rag_query_rewrite_test_support import (
    RecordingStructuredModel,
    RecordingStructuredRunnable,
)


@pytest.mark.asyncio
async def test_invoke_query_rewrite_returns_one_result_and_passes_config():
    from app.domains.rag.graph.nodes.query_rewrite import invoke_query_rewrite
    from app.domains.rag.graph.query_rewrite import (
        QueryRewriteResult,
        QueryRewriteStatus,
    )

    result = QueryRewriteResult(
        standalone_query="查询神木站本月实际版装车计划"
    )
    runnable = RecordingStructuredRunnable([result])
    model = RecordingStructuredModel(runnable)
    config: RunnableConfig = {
        "callbacks": [object()],
        "metadata": {"request_id": "request-1"},
    }

    update = await invoke_query_rewrite(
        {"original_query": "按实际版呢"},
        model=model,
        config=config,
    )

    assert model.schemas == [QueryRewriteResult]
    assert len(runnable.calls) == 1
    assert runnable.calls[0][1] is config
    assert update == {
        "standalone_query": "查询神木站本月实际版装车计划",
        "rewrite_status": QueryRewriteStatus.REWRITTEN,
        "rewrite_failure_code": None,
        "warnings": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runnable", "binding_error", "expected_code"),
    [
        (
            RecordingStructuredRunnable(error=RuntimeError("provider failed")),
            None,
            "model_invocation_failed",
        ),
        (
            RecordingStructuredRunnable([{"standalone_query": "   "}]),
            None,
            "invalid_output",
        ),
        (
            RecordingStructuredRunnable(),
            RuntimeError("structured output unavailable"),
            "model_invocation_failed",
        ),
    ],
)
async def test_invoke_query_rewrite_falls_back_once_without_provider_error(
    runnable,
    binding_error,
    expected_code,
):
    from app.domains.rag.graph.nodes.query_rewrite import invoke_query_rewrite
    from app.domains.rag.graph.query_rewrite import (
        QUERY_REWRITE_FALLBACK_WARNING,
    )

    model = RecordingStructuredModel(runnable, binding_error=binding_error)

    update = await invoke_query_rewrite(
        {"original_query": "查询运单 YD2026001"},
        model=model,
    )

    assert update == {
        "standalone_query": "查询运单 YD2026001",
        "rewrite_status": "fallback",
        "rewrite_failure_code": expected_code,
        "warnings": [QUERY_REWRITE_FALLBACK_WARNING],
    }
    assert len(model.schemas) == 1
    assert len(runnable.calls) <= 1
    assert "provider failed" not in repr(update)


@pytest.mark.asyncio
async def test_invoke_query_rewrite_does_not_convert_cancellation_to_fallback():
    from app.domains.rag.graph.nodes.query_rewrite import invoke_query_rewrite

    runnable = RecordingStructuredRunnable(error=asyncio.CancelledError())
    model = RecordingStructuredModel(runnable)

    with pytest.raises(asyncio.CancelledError):
        await invoke_query_rewrite(
            {"original_query": "查询本月运量"},
            model=model,
        )

    assert len(runnable.calls) == 1


@pytest.mark.asyncio
async def test_invoke_query_rewrite_rejects_invalid_input_before_model_call():
    from app.domains.rag.graph.nodes.query_rewrite import invoke_query_rewrite

    runnable = RecordingStructuredRunnable()
    model = RecordingStructuredModel(runnable)

    with pytest.raises(ValidationError):
        await invoke_query_rewrite(
            {
                "original_query": "按实际版呢",
                "conversation_context": [
                    {"role": "user", "content": "按实际版呢"}
                ],
            },
            model=model,
        )

    assert model.schemas == []
    assert runnable.calls == []


@pytest.mark.asyncio
async def test_query_rewrite_node_uses_runtime_model_and_preserves_warnings():
    from app.domains.rag.graph.context import RagRuntimeContext
    from app.domains.rag.graph.nodes.query_rewrite import query_rewrite_node
    from app.domains.rag.graph.query_rewrite import QueryRewriteResult

    runnable = RecordingStructuredRunnable(
        [QueryRewriteResult(standalone_query="查询神木站实际版装车计划")]
    )
    model = RecordingStructuredModel(runnable)
    config: RunnableConfig = {"metadata": {"request_id": "request-1"}}

    update = await query_rewrite_node(
        {
            "original_query": "按实际版呢",
            "conversation_context": [
                {
                    "role": "user",
                    "content": "查询神木站模拟版装车计划",
                }
            ],
            "business_context": {
                "intent": "BUSINESS_DATA_QUERY",
                "entities": {"departure_station": "神木站"},
            },
            "warnings": ["upstream_warning"],
        },
        config,
        Runtime(context=RagRuntimeContext(model=model)),
    )

    assert update["standalone_query"] == "查询神木站实际版装车计划"
    assert update["warnings"] == ["upstream_warning"]
    assert runnable.calls[0][1] is config


def test_query_rewrite_node_is_exported_from_nodes_package():
    from app.domains.rag.graph.nodes import (
        invoke_query_rewrite,
        query_rewrite_node,
    )

    assert callable(invoke_query_rewrite)
    assert callable(query_rewrite_node)


def test_importing_query_rewrite_node_does_not_initialize_runtime_resources(
    monkeypatch,
):
    from app.core import config
    from app.infrastructure import llm

    def explode(*args, **kwargs):
        raise AssertionError("domain import must not initialize resources")

    monkeypatch.setattr(config, "get_settings", explode)
    monkeypatch.setattr(llm, "create_chat_model", explode)
    for module_name in [
        "app.domains.rag.graph.nodes.query_rewrite",
        "app.domains.rag.graph.nodes",
        "app.domains.rag.graph.context",
    ]:
        sys.modules.pop(module_name, None)

    imported = importlib.import_module(
        "app.domains.rag.graph.nodes.query_rewrite"
    )

    assert callable(imported.query_rewrite_node)
