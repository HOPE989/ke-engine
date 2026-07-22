import pytest
from pydantic import ValidationError


def test_business_understanding_contract_has_only_v1_routes_intents_and_fields():
    from app.domains.chat.graph.business_understanding import (
        BusinessEntities,
        BusinessIntent,
        BusinessRoute,
        BusinessUnderstandingResult,
    )

    assert {item.value for item in BusinessRoute} == {
        "BUSINESS", "NON_BUSINESS", "CLARIFY"
    }
    assert {item.value for item in BusinessIntent} == {
        "POLICY_RULE_QA",
        "TRANSPORT_OPERATION_QA",
        "COAL_SALES_QA",
        "PROFESSIONAL_KNOWLEDGE_QA",
        "BUSINESS_DATA_QUERY",
        "OTHER_BUSINESS",
    }
    assert set(BusinessUnderstandingResult.model_fields) == {
        "reasoning", "route", "intent", "entities", "clarification_question"
    }
    assert set(BusinessEntities.model_fields) == {
        "operation_plan_no", "train_no", "formation_no", "contract_no",
        "document_type", "document_no", "customer", "supplier", "coal_type",
        "departure_station", "arrival_station", "railway_section", "time_range",
        "data_version", "metric_name", "exception_description",
    }
    assert {"related", "confidence", "business_domain"}.isdisjoint(
        BusinessUnderstandingResult.model_fields
    )


def test_business_entity_fields_have_model_facing_descriptions():
    from app.domains.chat.graph.business_understanding import BusinessEntities

    descriptions = {
        name: field.description
        for name, field in BusinessEntities.model_fields.items()
    }

    assert all(descriptions.values())
    assert "车站" in descriptions["departure_station"]
    assert "时间" in descriptions["time_range"]
    assert "指标" in descriptions["metric_name"]
    assert "运单" in descriptions["document_type"]
    assert "异常" in descriptions["exception_description"]


@pytest.mark.parametrize(
    "payload",
    [
        {"reasoning": "业务请求缺少意图", "route": "BUSINESS", "intent": None,
         "entities": {}, "clarification_question": None},
        {"reasoning": "非业务不得保留意图", "route": "NON_BUSINESS",
         "intent": "OTHER_BUSINESS", "entities": {}, "clarification_question": None},
        {"reasoning": "澄清问题不能为空", "route": "CLARIFY",
         "intent": "BUSINESS_DATA_QUERY", "entities": {},
         "clarification_question": "   "},
    ],
)
def test_business_understanding_rejects_inconsistent_cross_field_payload(payload):
    from app.domains.chat.graph.business_understanding import BusinessUnderstandingResult

    with pytest.raises(ValidationError):
        BusinessUnderstandingResult.model_validate(payload)


def test_business_understanding_rejects_unknown_intent_and_extra_legacy_fields():
    from app.domains.chat.graph.business_understanding import BusinessUnderstandingResult

    base = {
        "reasoning": "具体业务查询",
        "route": "BUSINESS",
        "intent": "PLAN_QUERY",
        "entities": {},
        "clarification_question": None,
        "related": True,
    }
    with pytest.raises(ValidationError):
        BusinessUnderstandingResult.model_validate(base)


def test_business_understanding_result_round_trips_json_checkpoint_data():
    from app.domains.chat.graph.business_understanding import BusinessUnderstandingResult

    result = BusinessUnderstandingResult.model_validate(
        {
            "reasoning": "查询运量数据",
            "route": "BUSINESS",
            "intent": "BUSINESS_DATA_QUERY",
            "entities": {"metric_name": "运量"},
            "clarification_question": None,
        }
    )

    dumped = result.model_dump(mode="json")
    restored = BusinessUnderstandingResult.model_validate(dumped)

    assert restored == result


def test_clarification_interrupt_payload_has_fixed_kind():
    from app.domains.chat.graph.business_understanding import ClarificationInterruptPayload

    payload = ClarificationInterruptPayload(question="请说明查询时间范围")

    assert payload.kind == "business_clarification"


@pytest.mark.parametrize("question", ["", "   "])
def test_clarification_interrupt_payload_rejects_blank_question(question):
    from app.domains.chat.graph.business_understanding import ClarificationInterruptPayload

    with pytest.raises(ValidationError):
        ClarificationInterruptPayload(question=question)


def test_clarification_interrupt_payload_rejects_extra_fields():
    from app.domains.chat.graph.business_understanding import ClarificationInterruptPayload

    with pytest.raises(ValidationError):
        ClarificationInterruptPayload(question="请补充信息", related=True)
