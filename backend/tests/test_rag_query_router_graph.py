import json

import pytest
from langgraph.graph import END, START

from rag_query_rewrite_test_support import (
    RecordingRetrieverFactory,
    RecordingStructuredModel,
    RecordingStructuredRunnable,
    document,
)


def test_rag_state_and_graph_exports_include_retrieval_contract():
    from app.domains.rag.graph import (
        COLLECT_RETRIEVAL_OUTCOMES_NODE,
        DOCUMENT_HYBRID_NODE,
        QUERY_ROUTER_NODE,
        RagState,
        collect_retrieval_outcomes_node,
        document_hybrid_node,
        query_router_node,
    )

    assert QUERY_ROUTER_NODE == "query_router"
    assert DOCUMENT_HYBRID_NODE == "document_hybrid"
    assert (
        COLLECT_RETRIEVAL_OUTCOMES_NODE
        == "collect_retrieval_outcomes"
    )
    assert "retrieval_plan" in RagState.__annotations__
    assert "document_retrieval_scope" in RagState.__annotations__
    assert "retrieval_outcomes" in RagState.__annotations__
    assert callable(query_router_node)
    assert callable(document_hybrid_node)
    assert callable(collect_retrieval_outcomes_node)


def test_rag_graph_compiles_only_registered_document_retriever():
    from app.domains.rag.graph import (
        COLLECT_RETRIEVAL_OUTCOMES_NODE,
        DOCUMENT_HYBRID_NODE,
        QUERY_REWRITE_NODE,
        build_rag_graph,
    )

    builder = build_rag_graph(
        model=RecordingStructuredModel(RecordingStructuredRunnable()),
        document_retriever_factory=RecordingRetrieverFactory(),
    )
    compiled = builder.compile()

    assert set(builder.nodes) == {
        "query_rewrite",
        "query_router",
        "document_hybrid",
        "collect_retrieval_outcomes",
    }
    assert builder.nodes[QUERY_REWRITE_NODE].retry_policy is None
    assert builder.nodes[DOCUMENT_HYBRID_NODE].retry_policy is None
    assert {
        (edge.source, edge.target)
        for edge in compiled.get_graph().edges
    } == {
        (START, "query_rewrite"),
        ("query_rewrite", "query_router"),
        ("query_router", "document_hybrid"),
        (
            "document_hybrid",
            COLLECT_RETRIEVAL_OUTCOMES_NODE,
        ),
        (COLLECT_RETRIEVAL_OUTCOMES_NODE, END),
    }
    assert compiled.checkpointer is None


def test_rag_graph_rejects_assembly_without_registered_retriever():
    from app.domains.rag.graph import build_rag_graph

    with pytest.raises(
        ValueError,
        match="at least one retriever node must be registered",
    ):
        build_rag_graph(
            model=RecordingStructuredModel(RecordingStructuredRunnable()),
            document_retriever_factory=None,
        )


@pytest.mark.asyncio
async def test_rag_graph_returns_serializable_document_outcome():
    from app.domains.rag.graph import build_rag_graph
    from app.domains.rag.graph.query_rewrite import QueryRewriteResult
    from app.domains.rag.graph.query_router import (
        QueryRouteResult,
        RetrieverKind,
    )

    runnable = RecordingStructuredRunnable(
        [
            QueryRewriteResult(
                standalone_query="查询合同付款周期"
            ),
            QueryRouteResult(
                selected_retrievers=[
                    RetrieverKind.DOCUMENT_HYBRID
                ],
                routing_reason="需要合同文档",
            ),
        ]
    )
    graph = build_rag_graph(
        model=RecordingStructuredModel(runnable),
        document_retriever_factory=RecordingRetrieverFactory(
            [document()]
        ),
    ).compile()

    result = await graph.ainvoke(
        {
            "original_query": "付款周期呢",
            "document_retrieval_scope": {
                "accessibleBy": ["team-a"]
            },
        }
    )

    assert result["retrieval_plan"] == {
        "selected_retrievers": ["DOCUMENT_HYBRID"],
        "routing_reason": "需要合同文档",
        "decision_source": "MODEL",
    }
    assert (
        result["retrieval_outcomes"]["DOCUMENT_HYBRID"]["status"]
        == "SUCCESS"
    )
    assert json.loads(json.dumps(result, ensure_ascii=False)) == result
    assert len(runnable.calls) == 2
