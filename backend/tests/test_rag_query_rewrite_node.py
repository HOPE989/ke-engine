import asyncio
import importlib
import sys

import pytest
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from rag_query_rewrite_test_support import (
    RecordingStructuredModel,
    RecordingStructuredRunnable,
)


@pytest.mark.asyncio
async def test_query_rewrite_node_returns_one_result_and_passes_config():
    from app.domains.rag.graph.nodes.query_rewrite import query_rewrite_node
    from app.domains.rag.graph.query_rewrite import QueryRewriteResult

    result = QueryRewriteResult(
        standalone_query="查询神木站本月实际版装车计划"
    )
    runnable = RecordingStructuredRunnable([result])
    model = RecordingStructuredModel(runnable)
    config: RunnableConfig = {
        "callbacks": [object()],
        "metadata": {"request_id": "request-1"},
    }

    update = await query_rewrite_node(
        {"original_query": "按实际版呢"},
        model=model,
        config=config,
    )

    assert model.schemas == [QueryRewriteResult]
    assert len(runnable.calls) == 1
    assert runnable.calls[0][1] is config
    assert update == {
        "standalone_query": "查询神木站本月实际版装车计划",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runnable", "binding_error"),
    [
        (
            RecordingStructuredRunnable(error=RuntimeError("provider failed")),
            None,
        ),
        (
            RecordingStructuredRunnable([{"standalone_query": "   "}]),
            None,
        ),
        (
            RecordingStructuredRunnable(),
            RuntimeError("structured output unavailable"),
        ),
    ],
)
async def test_query_rewrite_node_falls_back_once_without_provider_error(
    runnable,
    binding_error,
):
    from app.domains.rag.graph.nodes.query_rewrite import query_rewrite_node
    model = RecordingStructuredModel(runnable, binding_error=binding_error)

    update = await query_rewrite_node(
        {"original_query": "查询运单 YD2026001"},
        model=model,
    )

    assert update == {
        "standalone_query": "查询运单 YD2026001",
    }
    assert len(model.schemas) == 1
    assert len(runnable.calls) <= 1
    assert "provider failed" not in repr(update)


@pytest.mark.asyncio
async def test_query_rewrite_node_does_not_convert_cancellation_to_fallback():
    from app.domains.rag.graph.nodes.query_rewrite import query_rewrite_node

    runnable = RecordingStructuredRunnable(error=asyncio.CancelledError())
    model = RecordingStructuredModel(runnable)

    with pytest.raises(asyncio.CancelledError):
        await query_rewrite_node(
            {"original_query": "查询本月运量"},
            model=model,
        )

    assert len(runnable.calls) == 1


@pytest.mark.asyncio
async def test_query_rewrite_node_rejects_invalid_input_before_model_call():
    from app.domains.rag.graph.nodes.query_rewrite import query_rewrite_node

    runnable = RecordingStructuredRunnable()
    model = RecordingStructuredModel(runnable)

    with pytest.raises(ValidationError):
        await query_rewrite_node(
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


def test_query_rewrite_node_is_exported_from_nodes_package():
    from app.domains.rag.graph.nodes import query_rewrite_node

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
    ]:
        sys.modules.pop(module_name, None)

    imported = importlib.import_module(
        "app.domains.rag.graph.nodes.query_rewrite"
    )

    assert callable(imported.query_rewrite_node)
