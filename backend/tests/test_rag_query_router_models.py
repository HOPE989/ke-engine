import pytest
from pydantic import ValidationError


def test_query_router_input_accepts_standalone_query_and_available_capabilities():
    from app.domains.rag.graph.query_router import (
        QueryRouterInput,
        RetrieverKind,
    )

    request = QueryRouterInput(
        standalone_query="查询本月各客户发运量及统计口径",
        available_retrievers=[
            RetrieverKind.DOCUMENT_HYBRID,
            RetrieverKind.SQL,
        ],
    )

    assert request.standalone_query == "查询本月各客户发运量及统计口径"
    assert request.available_retrievers == [
        RetrieverKind.DOCUMENT_HYBRID,
        RetrieverKind.SQL,
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "standalone_query": "",
            "available_retrievers": ["DOCUMENT_HYBRID"],
        },
        {
            "standalone_query": "查询本月运量",
            "available_retrievers": [],
        },
        {
            "standalone_query": "查询本月运量",
            "available_retrievers": ["UNKNOWN"],
        },
        {
            "standalone_query": "查询本月运量",
            "available_retrievers": ["SQL"],
            "conversation_id": "conversation-1",
        },
    ],
)
def test_query_router_input_rejects_invalid_or_caller_owned_fields(payload):
    from app.domains.rag.graph.query_router import QueryRouterInput

    with pytest.raises(ValidationError):
        QueryRouterInput.model_validate(payload)


def test_query_route_result_accepts_multi_select_and_rejects_extra_fields():
    from app.domains.rag.graph.query_router import (
        QueryRouteResult,
        RetrieverKind,
    )

    result = QueryRouteResult(
        selected_retrievers=[
            RetrieverKind.SQL,
            RetrieverKind.DOCUMENT_HYBRID,
        ],
        routing_reason="需要业务统计值和统计口径两类证据",
    )

    assert result.selected_retrievers == [
        RetrieverKind.SQL,
        RetrieverKind.DOCUMENT_HYBRID,
    ]

    with pytest.raises(ValidationError):
        QueryRouteResult.model_validate(
            {
                **result.model_dump(mode="json"),
                "confidence": 0.9,
            }
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "selected_retrievers": [],
            "routing_reason": "没有选择",
        },
        {
            "selected_retrievers": ["SQL"],
            "routing_reason": " ",
        },
        {
            "selected_retrievers": ["UNKNOWN"],
            "routing_reason": "未知能力",
        },
    ],
)
def test_query_route_result_rejects_invalid_output(payload):
    from app.domains.rag.graph.query_router import QueryRouteResult

    with pytest.raises(ValidationError):
        QueryRouteResult.model_validate(payload)


def test_retrieval_plan_and_update_have_only_execution_contract_fields():
    import app.domains.rag.graph.query_router as query_router
    from app.domains.rag.graph.query_router import (
        QueryRouterUpdate,
        RetrievalPlan,
        RoutingDecisionSource,
        RetrieverKind,
    )

    plan = RetrievalPlan(
        selected_retrievers=[RetrieverKind.GRAPH],
        routing_reason="需要查询已建模的运输路径",
        decision_source=RoutingDecisionSource.MODEL,
    )

    assert plan.model_dump(mode="json") == {
        "selected_retrievers": ["GRAPH"],
        "routing_reason": "需要查询已建模的运输路径",
        "decision_source": "MODEL",
    }
    assert set(QueryRouterUpdate.__annotations__) == {"retrieval_plan"}
    assert issubclass(query_router.QueryRouterUnavailable, Exception)
    for field in ["confidence", "sql", "cypher", "queries"]:
        assert field not in RetrievalPlan.model_fields


def test_query_router_contracts_are_exported_from_package():
    from app.domains.rag.graph.query_router import (
        QueryRouteResult,
        QueryRouterInput,
        QueryRouterUnavailable,
        QueryRouterUpdate,
        RetrievalPlan,
        RetrieverKind,
        RoutingDecisionSource,
    )

    assert all(
        item is not None
        for item in [
            QueryRouteResult,
            QueryRouterInput,
            QueryRouterUnavailable,
            QueryRouterUpdate,
            RetrievalPlan,
            RetrieverKind,
            RoutingDecisionSource,
        ]
    )
