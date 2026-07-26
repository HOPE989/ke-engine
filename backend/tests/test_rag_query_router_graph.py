import json

import pytest
from langgraph.graph import END, START

from rag_query_rewrite_test_support import (
    RecordingStructuredModel,
    RecordingStructuredRunnable,
)


def test_rag_state_and_graph_exports_include_query_router_contract():
    from app.domains.rag.graph import (
        QUERY_ROUTER_NODE,
        RagState,
        query_router_node,
    )

    assert QUERY_ROUTER_NODE == "query_router"
    assert "retrieval_plan" in RagState.__annotations__
    assert callable(query_router_node)


def test_rag_graph_compiles_rewrite_then_router_with_static_edges():
    from app.domains.rag.graph import (
        build_rag_graph,
    )
    from app.domains.rag.graph.query_router import RetrieverKind

    builder = build_rag_graph(
        model=RecordingStructuredModel(RecordingStructuredRunnable()),
        available_retrievers=tuple(RetrieverKind),
    )
    compiled = builder.compile()

    assert set(builder.nodes) == {"query_rewrite", "query_router"}
    assert builder.nodes["query_rewrite"].retry_policy is None
    assert builder.nodes["query_router"].retry_policy is None
    assert {(edge.source, edge.target) for edge in compiled.get_graph().edges} == {
        (START, "query_rewrite"),
        ("query_rewrite", "query_router"),
        ("query_router", END),
    }
    assert compiled.checkpointer is None


def test_rag_graph_rejects_empty_router_capabilities_at_assembly():
    from app.domains.rag.graph import build_rag_graph

    with pytest.raises(
        ValueError,
        match="available_retrievers must not be empty",
    ):
        build_rag_graph(
            model=RecordingStructuredModel(RecordingStructuredRunnable()),
            available_retrievers=(),
        )


@pytest.mark.asyncio
async def test_rag_graph_returns_serializable_rewrite_and_retrieval_plan():
    from app.domains.rag.graph import build_rag_graph
    from app.domains.rag.graph.query_rewrite import QueryRewriteResult
    from app.domains.rag.graph.query_router import (
        QueryRouteResult,
        RetrieverKind,
    )

    runnable = RecordingStructuredRunnable(
        [
            QueryRewriteResult(
                standalone_query="查询本月各客户发运量及统计口径"
            ),
            QueryRouteResult(
                selected_retrievers=[
                    RetrieverKind.SQL,
                    RetrieverKind.DOCUMENT_HYBRID,
                ],
                routing_reason="需要统计数据和文档口径",
            ),
        ]
    )
    graph = build_rag_graph(
        model=RecordingStructuredModel(runnable),
        available_retrievers=tuple(RetrieverKind),
    ).compile()

    result = await graph.ainvoke(
        {"original_query": "本月各客户发运量和口径呢"}
    )

    assert result["standalone_query"] == "查询本月各客户发运量及统计口径"
    assert result["retrieval_plan"] == {
        "selected_retrievers": ["DOCUMENT_HYBRID", "SQL"],
        "routing_reason": "需要统计数据和文档口径",
        "decision_source": "MODEL",
    }
    assert json.loads(json.dumps(result, ensure_ascii=False)) == result
    assert len(runnable.calls) == 2
