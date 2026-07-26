import asyncio

import pytest
from langchain_core.runnables import RunnableConfig

from rag_query_rewrite_test_support import (
    RecordingStructuredModel,
    RecordingStructuredRunnable,
)


@pytest.mark.asyncio
async def test_query_router_node_returns_model_plan_and_passes_config():
    from app.domains.rag.graph.nodes.query_router import query_router_node
    from app.domains.rag.graph.query_router import (
        QueryRouteResult,
        RetrieverKind,
    )

    result = QueryRouteResult(
        selected_retrievers=[RetrieverKind.SQL],
        routing_reason="需要查询结构化业务统计",
    )
    runnable = RecordingStructuredRunnable([result])
    model = RecordingStructuredModel(runnable)
    config: RunnableConfig = {
        "callbacks": [object()],
        "metadata": {"request_id": "request-router-1"},
    }

    command = await query_router_node(
        {"standalone_query": "查询本月各客户发运量"},
        model=model,
        retriever_destinations={
            RetrieverKind.DOCUMENT_HYBRID: "document_hybrid",
            RetrieverKind.SQL: "sql",
        },
        config=config,
    )

    assert model.schemas == [QueryRouteResult]
    assert model.structured_output_calls == [
        {
            "schema": QueryRouteResult,
            "method": "json_mode",
        }
    ]
    assert len(runnable.calls) == 1
    assert runnable.calls[0][1] is config
    assert command.update == {
        "retrieval_plan": {
            "selected_retrievers": ["SQL"],
            "routing_reason": "需要查询结构化业务统计",
            "decision_source": "MODEL",
        }
    }
    assert command.goto == ["sql"]


@pytest.mark.asyncio
async def test_query_router_node_deduplicates_and_canonically_orders_routes():
    from app.domains.rag.graph.nodes.query_router import query_router_node
    from app.domains.rag.graph.query_router import (
        QueryRouteResult,
        RetrieverKind,
    )

    runnable = RecordingStructuredRunnable(
        [
            QueryRouteResult(
                selected_retrievers=[
                    RetrieverKind.SQL,
                    RetrieverKind.DOCUMENT_HYBRID,
                    RetrieverKind.SQL,
                ],
                routing_reason="需要统计值与统计口径",
            )
        ]
    )

    command = await query_router_node(
        {"standalone_query": "查询本月发运量及统计口径"},
        model=RecordingStructuredModel(runnable),
        retriever_destinations={
            RetrieverKind.DOCUMENT_HYBRID: "document_hybrid",
            RetrieverKind.SQL: "sql",
            RetrieverKind.GRAPH: "graph",
        },
    )

    assert command.update["retrieval_plan"]["selected_retrievers"] == [
        "DOCUMENT_HYBRID",
        "SQL",
    ]
    assert command.update["retrieval_plan"]["decision_source"] == "MODEL"
    assert command.goto == ["document_hybrid", "sql"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "error", "binding_error"),
    [
        ((), RuntimeError("provider failed"), None),
        ((), TimeoutError("provider timed out"), None),
        ([{"selected_retrievers": [], "routing_reason": "无"}], None, None),
        (
            [
                {
                    "selected_retrievers": ["UNKNOWN"],
                    "routing_reason": "未知",
                }
            ],
            None,
            None,
        ),
        (
            [
                {
                    "selected_retrievers": ["GRAPH"],
                    "routing_reason": "需要图关系",
                }
            ],
            None,
            None,
        ),
        ((), None, RuntimeError("structured output unavailable")),
    ],
)
async def test_query_router_node_falls_back_to_document_once(
    result,
    error,
    binding_error,
):
    from app.domains.rag.graph.nodes.query_router import query_router_node
    from app.domains.rag.graph.query_router import RetrieverKind

    runnable = RecordingStructuredRunnable(result, error=error)
    model = RecordingStructuredModel(
        runnable,
        binding_error=binding_error,
    )

    command = await query_router_node(
        {"standalone_query": "查询本月发运量"},
        model=model,
        retriever_destinations={
            RetrieverKind.DOCUMENT_HYBRID: "document_hybrid",
            RetrieverKind.SQL: "sql",
        },
    )

    assert command.update == {
        "retrieval_plan": {
            "selected_retrievers": ["DOCUMENT_HYBRID"],
            "routing_reason": "路由不可用，使用文档混合检索",
            "decision_source": "FALLBACK",
        }
    }
    assert command.goto == ["document_hybrid"]
    assert len(model.schemas) == 1
    assert len(runnable.calls) <= 1
    assert "provider failed" not in repr(command)


@pytest.mark.asyncio
async def test_query_router_node_raises_stable_error_without_document_fallback():
    from app.domains.rag.graph.nodes.query_router import query_router_node
    from app.domains.rag.graph.query_router import (
        QueryRouterUnavailable,
        RetrieverKind,
    )

    runnable = RecordingStructuredRunnable(
        error=RuntimeError("database endpoint leaked")
    )

    with pytest.raises(
        QueryRouterUnavailable,
        match="query router unavailable",
    ) as exc_info:
        await query_router_node(
            {"standalone_query": "查询本月发运量"},
            model=RecordingStructuredModel(runnable),
            retriever_destinations={RetrieverKind.SQL: "sql"},
        )

    assert "database endpoint leaked" not in str(exc_info.value)
    assert len(runnable.calls) == 1


@pytest.mark.asyncio
async def test_query_router_node_does_not_convert_cancellation_to_fallback():
    from app.domains.rag.graph.nodes.query_router import query_router_node
    from app.domains.rag.graph.query_router import RetrieverKind

    runnable = RecordingStructuredRunnable(error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await query_router_node(
            {"standalone_query": "查询本月发运量"},
            model=RecordingStructuredModel(runnable),
            retriever_destinations={
                RetrieverKind.DOCUMENT_HYBRID: "document_hybrid"
            },
        )

    assert len(runnable.calls) == 1


def test_query_router_node_is_exported_from_nodes_package():
    from app.domains.rag.graph.nodes import query_router_node

    assert callable(query_router_node)
