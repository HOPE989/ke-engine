import json

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langgraph.graph import END, START

from rag_query_rewrite_test_support import (
    RecordingStructuredModel,
    RecordingStructuredRunnable,
)


class RecordingGraphCallback(BaseCallbackHandler):
    def __init__(self):
        self.chain_inputs = []
        self.chain_outputs = []

    def on_chain_start(self, serialized, inputs, **kwargs):
        self.chain_inputs.append(inputs)

    def on_chain_end(self, outputs, **kwargs):
        self.chain_outputs.append(outputs)


def test_query_rewrite_graph_has_one_node_no_retry_and_no_checkpointer():
    from app.domains.rag.graph import (
        QUERY_REWRITE_NODE,
        RagRuntimeContext,
        build_query_rewrite_graph,
    )

    builder = build_query_rewrite_graph()
    compiled = builder.compile()

    assert QUERY_REWRITE_NODE == "query_rewrite"
    assert builder.context_schema is RagRuntimeContext
    assert set(builder.nodes) == {"query_rewrite"}
    assert builder.nodes["query_rewrite"].retry_policy is None
    assert {(edge.source, edge.target) for edge in compiled.get_graph().edges} == {
        (START, "query_rewrite"),
        ("query_rewrite", END),
    }
    assert compiled.checkpointer is None


@pytest.mark.asyncio
async def test_bound_graph_keeps_requests_isolated_and_serializable():
    from app.domains.rag.graph import build_query_rewrite_graph
    from app.domains.rag.graph.query_rewrite import QueryRewriteResult

    runnable = RecordingStructuredRunnable(
        [
            QueryRewriteResult(standalone_query="查询第一份运单"),
            QueryRewriteResult(standalone_query="查询第二份合同"),
        ]
    )
    graph = build_query_rewrite_graph(
        bound_model=RecordingStructuredModel(runnable)
    ).compile()

    first = await graph.ainvoke({"original_query": "第一份呢"})
    second = await graph.ainvoke({"original_query": "第二份呢"})

    assert first["standalone_query"] == "查询第一份运单"
    assert second["standalone_query"] == "查询第二份合同"
    assert first["original_query"] == "第一份呢"
    assert second["original_query"] == "第二份呢"
    assert json.loads(json.dumps(second, ensure_ascii=False))["warnings"] == []


@pytest.mark.asyncio
async def test_runtime_graph_uses_context_model_and_returns_fallback_state():
    from app.domains.rag.graph import (
        RagRuntimeContext,
        build_query_rewrite_graph,
    )

    runnable = RecordingStructuredRunnable(error=RuntimeError("unavailable"))
    model = RecordingStructuredModel(runnable)

    result = await build_query_rewrite_graph().compile().ainvoke(
        {"original_query": "查询本月运量"},
        context=RagRuntimeContext(model=model),
    )

    assert result["standalone_query"] == "查询本月运量"
    assert result["rewrite_status"] == "fallback"
    assert result["rewrite_failure_code"] == "model_invocation_failed"
    assert result["warnings"] == ["query_rewrite_fallback"]
    assert len(runnable.calls) == 1


@pytest.mark.asyncio
async def test_bound_graph_passes_metadata_and_callbacks_to_model_call():
    from app.domains.rag.graph import build_query_rewrite_graph
    from app.domains.rag.graph.query_rewrite import QueryRewriteResult

    runnable = RecordingStructuredRunnable(
        [QueryRewriteResult(standalone_query="查询本月运量")]
    )
    handler = RecordingGraphCallback()
    graph = build_query_rewrite_graph(
        bound_model=RecordingStructuredModel(runnable)
    ).compile()

    await graph.ainvoke(
        {"original_query": "查本月运量"},
        config={
            "callbacks": [handler],
            "metadata": {"request_id": "request-graph-1"},
        },
    )

    received_config = runnable.calls[0][1]
    assert received_config["metadata"]["request_id"] == "request-graph-1"
    assert "callbacks" in received_config
    assert any(
        isinstance(value, dict)
        and value.get("original_query") == "查本月运量"
        for value in handler.chain_inputs
    )
    assert any(
        isinstance(value, dict)
        and value.get("standalone_query") == "查询本月运量"
        and value.get("rewrite_status") == "rewritten"
        for value in handler.chain_outputs
    )
