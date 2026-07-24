import pytest
from pydantic import ValidationError


def test_query_rewrite_input_preserves_ordered_context_and_business_context():
    from app.domains.rag.graph.query_rewrite import QueryRewriteInput

    request = QueryRewriteInput.model_validate(
        {
            "original_query": "按实际版呢",
            "conversation_context": [
                {"role": "user", "content": "查询神木站本月模拟版装车计划"},
                {"role": "assistant", "content": "你想了解计划的哪个指标？"},
            ],
            "business_context": {
                "intent": "BUSINESS_DATA_QUERY",
                "entities": {"departure_station": "神木站"},
            },
        }
    )

    assert [message.role for message in request.conversation_context] == [
        "user",
        "assistant",
    ]
    assert request.business_context is not None
    assert request.business_context.entities == {"departure_station": "神木站"}


@pytest.mark.parametrize(
    "payload",
    [
        {"original_query": ""},
        {"original_query": "   "},
        {
            "original_query": "按实际版呢",
            "conversation_context": [
                {"role": "user", "content": " 按实际版呢 "}
            ],
        },
        {
            "original_query": "查询运单",
            "conversation_id": "conversation-1",
        },
    ],
)
def test_query_rewrite_input_rejects_invalid_or_caller_owned_fields(payload):
    from app.domains.rag.graph.query_rewrite import QueryRewriteInput

    with pytest.raises(ValidationError):
        QueryRewriteInput.model_validate(payload)


@pytest.mark.parametrize("standalone_query", ["", "   ", "查", "《"])
def test_query_rewrite_result_rejects_incomplete_query(standalone_query):
    from app.domains.rag.graph.query_rewrite import QueryRewriteResult

    with pytest.raises(ValidationError):
        QueryRewriteResult(standalone_query=standalone_query)


def test_query_rewrite_update_contains_only_standalone_query():
    import app.domains.rag.graph.query_rewrite as query_rewrite
    from app.domains.rag.graph.query_rewrite import QueryRewriteUpdate

    assert not hasattr(query_rewrite, "QueryRewriteStatus")
    assert not hasattr(query_rewrite, "QueryRewriteFailureCode")
    assert set(QueryRewriteUpdate.__annotations__) == {"standalone_query"}
    assert "rewrite_status" not in QueryRewriteUpdate.__annotations__
    assert "rewrite_failure_code" not in QueryRewriteUpdate.__annotations__
    assert "warnings" not in QueryRewriteUpdate.__annotations__
