import json
from pathlib import Path

import pytest
from langchain_core.callbacks import BaseCallbackHandler

from rag_query_rewrite_test_support import (
    RecordingRetrieverFactory,
    RecordingStructuredModel,
    RecordingStructuredRunnable,
    document,
)


class RecordingGraphCallback(BaseCallbackHandler):
    def __init__(self):
        self.chain_inputs = []
        self.chain_outputs = []

    def on_chain_start(self, serialized, inputs, **kwargs):
        self.chain_inputs.append(inputs)

    def on_chain_end(self, outputs, **kwargs):
        self.chain_outputs.append(outputs)


def test_rag_state_is_request_scoped_and_serializable():
    from app.domains.rag.graph.state import RagState

    expected_fields = {
        "standalone_query",
        "retrieval_plan",
        "document_retrieval_scope",
        "retrieval_outcomes",
    }
    assert expected_fields <= set(RagState.__annotations__)

    state: RagState = {
        "standalone_query": "查询合同付款周期",
        "document_retrieval_scope": {
            "accessibleBy": ["team-a"]
        },
        "retrieval_plan": {
            "selected_retrievers": ["DOCUMENT_HYBRID"],
            "routing_reason": "需要合同文档",
            "decision_source": "MODEL",
        },
        "retrieval_outcomes": {
            "DOCUMENT_HYBRID": {"status": "EMPTY"}
        },
    }

    assert json.loads(json.dumps(state, ensure_ascii=False)) == state


def test_rag_graph_does_not_define_runtime_dependency_context():
    import app.domains.rag.graph as graph_package

    graph_dir = Path(graph_package.__file__).parent

    assert "RagRuntimeContext" not in graph_package.__all__
    assert not (graph_dir / "context.py").exists()


@pytest.mark.asyncio
async def test_assembled_rag_graph_keeps_requests_isolated():
    from app.domains.rag.graph import build_rag_graph
    from app.domains.rag.graph.query_router import (
        QueryRouteResult,
        RetrieverKind,
    )

    runnable = RecordingStructuredRunnable(
        [
            QueryRouteResult(
                selected_retrievers=[
                    RetrieverKind.DOCUMENT_HYBRID
                ],
                routing_reason="需要第一份文档",
            ),
            QueryRouteResult(
                selected_retrievers=[
                    RetrieverKind.DOCUMENT_HYBRID
                ],
                routing_reason="需要第二份文档",
            ),
        ]
    )
    factory = RecordingRetrieverFactory([document()])
    graph = build_rag_graph(
        model=RecordingStructuredModel(runnable),
        document_retriever_factory=factory,
    ).compile()

    first = await graph.ainvoke(
        {
            "standalone_query": "查询第一份合同",
            "document_retrieval_scope": {
                "accessibleBy": ["team-a"]
            },
        }
    )
    second = await graph.ainvoke(
        {
            "standalone_query": "查询第二份合同",
            "document_retrieval_scope": {
                "accessibleBy": ["team-b"]
            },
        }
    )

    assert first["standalone_query"] == "查询第一份合同"
    assert second["standalone_query"] == "查询第二份合同"
    assert factory.scopes[0].accessible_by == ("team-a",)
    assert factory.scopes[1].accessible_by == ("team-b",)
    assert "warnings" not in second


@pytest.mark.asyncio
async def test_assembled_rag_graph_returns_fallback_document_outcome():
    from app.domains.rag.graph import build_rag_graph

    runnable = RecordingStructuredRunnable(
        error=RuntimeError("unavailable")
    )
    result = await build_rag_graph(
        model=RecordingStructuredModel(runnable),
        document_retriever_factory=RecordingRetrieverFactory(),
    ).compile().ainvoke(
        {
            "standalone_query": "查询合同",
            "document_retrieval_scope": {
                "accessibleBy": ["team-a"]
            },
        }
    )

    assert result["retrieval_plan"]["decision_source"] == "FALLBACK"
    assert (
        result["retrieval_outcomes"]["DOCUMENT_HYBRID"]["status"]
        == "EMPTY"
    )
    assert len(runnable.calls) == 1


@pytest.mark.asyncio
async def test_assembled_rag_graph_passes_config_to_models_and_retriever():
    from app.domains.rag.graph import build_rag_graph
    from app.domains.rag.graph.query_router import (
        QueryRouteResult,
        RetrieverKind,
    )

    runnable = RecordingStructuredRunnable(
        [
            QueryRouteResult(
                selected_retrievers=[
                    RetrieverKind.DOCUMENT_HYBRID
                ],
                routing_reason="需要文档",
            ),
        ]
    )
    factory = RecordingRetrieverFactory([document()])
    handler = RecordingGraphCallback()
    graph = build_rag_graph(
        model=RecordingStructuredModel(runnable),
        document_retriever_factory=factory,
    ).compile()

    await graph.ainvoke(
        {
            "standalone_query": "查询合同",
            "document_retrieval_scope": {
                "accessibleBy": ["team-a"]
            },
        },
        config={
            "callbacks": [handler],
            "metadata": {"request_id": "request-graph-1"},
        },
    )

    for _, received_config in runnable.calls:
        assert (
            received_config["metadata"]["request_id"]
            == "request-graph-1"
        )
    retriever_config = factory.retrievers[0].calls[0][1]
    assert retriever_config["metadata"]["request_id"] == "request-graph-1"
    assert any(
        isinstance(value, dict)
        and value.get("standalone_query") == "查询合同"
        for value in handler.chain_inputs
    )
