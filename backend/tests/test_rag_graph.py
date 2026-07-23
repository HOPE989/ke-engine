import json
from pathlib import Path

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


def test_rag_state_contains_serializable_rewrite_slice_and_can_expand():
    from app.domains.rag.graph.state import RagState

    current_rewrite_fields = {
        "original_query",
        "conversation_context",
        "business_context",
        "standalone_query",
        "rewrite_status",
        "rewrite_failure_code",
        "warnings",
    }
    assert current_rewrite_fields <= set(RagState.__annotations__)

    state: RagState = {
        "original_query": "查询运单 YD2026001",
        "conversation_context": [],
        "business_context": None,
        "standalone_query": "查询运单 YD2026001",
        "rewrite_status": "rewritten",
        "rewrite_failure_code": None,
        "warnings": [],
    }

    assert json.loads(json.dumps(state, ensure_ascii=False))["warnings"] == []


def test_rag_graph_starts_with_rewrite_node_no_retry_or_checkpointer():
    from app.domains.rag.graph import (
        QUERY_REWRITE_NODE,
        build_rag_graph,
    )

    model = RecordingStructuredModel(RecordingStructuredRunnable())
    builder = build_rag_graph(model=model)
    compiled = builder.compile()

    assert QUERY_REWRITE_NODE == "query_rewrite"
    assert builder.context_schema is None
    assert set(builder.nodes) == {"query_rewrite"}
    assert builder.nodes["query_rewrite"].retry_policy is None
    assert {(edge.source, edge.target) for edge in compiled.get_graph().edges} == {
        (START, "query_rewrite"),
        ("query_rewrite", END),
    }
    assert compiled.checkpointer is None


def test_rag_graph_does_not_define_runtime_dependency_context():
    import app.domains.rag.graph as graph_package

    graph_dir = Path(graph_package.__file__).parent

    assert "RagRuntimeContext" not in graph_package.__all__
    assert not (graph_dir / "context.py").exists()


@pytest.mark.asyncio
async def test_assembled_rag_graph_keeps_requests_isolated_and_serializable():
    from app.domains.rag.graph import build_rag_graph
    from app.domains.rag.graph.query_rewrite import QueryRewriteResult

    runnable = RecordingStructuredRunnable(
        [
            QueryRewriteResult(standalone_query="查询第一份运单"),
            QueryRewriteResult(standalone_query="查询第二份合同"),
        ]
    )
    graph = build_rag_graph(
        model=RecordingStructuredModel(runnable)
    ).compile()

    first = await graph.ainvoke({"original_query": "第一份呢"})
    second = await graph.ainvoke({"original_query": "第二份呢"})

    assert first["standalone_query"] == "查询第一份运单"
    assert second["standalone_query"] == "查询第二份合同"
    assert first["original_query"] == "第一份呢"
    assert second["original_query"] == "第二份呢"
    assert json.loads(json.dumps(second, ensure_ascii=False))["warnings"] == []


@pytest.mark.asyncio
async def test_assembled_rag_graph_returns_fallback_state():
    from app.domains.rag.graph import build_rag_graph

    runnable = RecordingStructuredRunnable(error=RuntimeError("unavailable"))
    model = RecordingStructuredModel(runnable)

    result = await build_rag_graph(model=model).compile().ainvoke(
        {"original_query": "查询本月运量"}
    )

    assert result["standalone_query"] == "查询本月运量"
    assert result["rewrite_status"] == "fallback"
    assert result["rewrite_failure_code"] == "model_invocation_failed"
    assert result["warnings"] == ["query_rewrite_fallback"]
    assert len(runnable.calls) == 1


@pytest.mark.asyncio
async def test_assembled_rag_graph_passes_config_to_model_call():
    from app.domains.rag.graph import build_rag_graph
    from app.domains.rag.graph.query_rewrite import QueryRewriteResult

    runnable = RecordingStructuredRunnable(
        [QueryRewriteResult(standalone_query="查询本月运量")]
    )
    handler = RecordingGraphCallback()
    graph = build_rag_graph(
        model=RecordingStructuredModel(runnable)
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
