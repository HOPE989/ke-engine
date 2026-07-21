from app.domains.chat.graph.business_understanding.models import BusinessEntities


def test_evaluation_dataset_covers_required_boundary_groups():
    from app.domains.chat.graph.business_understanding.evaluation import (
        load_evaluation_cases,
    )

    cases = load_evaluation_cases()
    categories = {case.category for case in cases}
    assert {
        "public_passenger_negative",
        "freight_document_knowledge",
        "freight_document_lookup",
        "policy_vs_professional",
        "transport_vs_coal_sales",
        "multi_turn_ellipsis",
        "focused_clarification",
        "optional_entity_no_clarification",
        "unsupported_schema",
    } <= categories
    assert all(
        case.expected_key_entities.keys() <= BusinessEntities.model_fields.keys()
        for case in cases
    )


def test_evaluation_scorer_reports_each_dimension_independently():
    from app.domains.chat.graph.business_understanding.evaluation import (
        EvaluationCase,
        score_evaluation_cases,
    )
    from app.domains.chat.graph.business_understanding.models import (
        BusinessIntent,
        BusinessRoute,
    )

    expected = EvaluationCase(
        id="scorer-case",
        category="unit",
        messages=[],
        expected_route=BusinessRoute.BUSINESS,
        expected_intent=BusinessIntent.BUSINESS_DATA_QUERY,
        expected_key_entities={"document_type": "运单", "document_no": "YD2026001"},
        expected_clarification_contains=None,
    )
    actual = {
        "reasoning": "识别为运单查询",
        "route": "BUSINESS",
        "intent": "TRANSPORT_OPERATION_QA",
        "entities": {"document_type": "运单", "document_no": "YD9999999"},
        "clarification_question": None,
    }

    score = score_evaluation_cases(expected, actual)

    assert score.route == (1, 1)
    assert score.intent == (0, 1)
    assert score.key_entities == (1, 2)
    assert score.clarification == (1, 1)
    assert score.schema_validity == (1, 1)
