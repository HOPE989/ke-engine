import pytest
from pydantic import ValidationError

from app.domains.chat.graph.query_contextualization import (
    QueryContextInput,
    QueryContextResult,
    QueryContextUpdate,
)


def test_query_context_input_preserves_history_and_business_context():
    request = QueryContextInput.model_validate(
        {
            "original_query": "按实际版呢",
            "conversation_context": [
                {"role": "user", "content": "查询神木站本月模拟版装车计划"},
                {"role": "assistant", "content": "你想了解哪个指标？"},
            ],
            "business_context": {
                "intent": "BUSINESS_DATA_QUERY",
                "entities": {"departure_station": "神木站"},
            },
        }
    )

    assert [item.role for item in request.conversation_context] == [
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
        {"original_query": "查询运单", "conversation_id": "1"},
    ],
)
def test_query_context_input_rejects_invalid_fields(payload):
    with pytest.raises(ValidationError):
        QueryContextInput.model_validate(payload)


@pytest.mark.parametrize("standalone_query", ["", "   ", "查", "《"])
def test_query_context_result_rejects_incomplete_query(standalone_query):
    with pytest.raises(ValidationError):
        QueryContextResult(standalone_query=standalone_query)


def test_query_context_update_contains_only_standalone_query():
    assert set(QueryContextUpdate.__annotations__) == {"standalone_query"}
