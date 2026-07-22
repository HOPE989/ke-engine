from app.domains.chat.graph.business_understanding.models import BusinessEntities


def test_evaluation_dataset_covers_required_boundary_groups():
    from app.domains.chat.graph.business_understanding.evaluation import (
        load_evaluation_cases,
    )

    cases = load_evaluation_cases()
    categories = {case.category for case in cases}
    required_categories = {
        "public_passenger_negative",
        "freight_document_knowledge",
        "freight_document_lookup",
        "policy_vs_professional",
        "transport_vs_coal_sales",
        "multi_turn_ellipsis",
        "focused_clarification",
        "optional_entity_no_clarification",
        "unsupported_schema",
    }
    assert required_categories <= categories
    cases_by_category = {
        category: [case for case in cases if case.category == category]
        for category in required_categories
    }
    assert not {
        category
        for category, category_cases in cases_by_category.items()
        if len(category_cases) < 2
    }
    for category, category_cases in cases_by_category.items():
        assert len({case.id for case in category_cases}) >= 2, category
        assert len(
            {
                tuple((message["role"], message["content"]) for message in case.messages)
                for case in category_cases
            }
        ) >= 2, category
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


def test_deterministic_contract_evaluator_summary_reports_all_five_dimensions():
    from app.domains.chat.graph.business_understanding.evaluation import (
        load_evaluation_cases,
        score_evaluation_cases,
    )

    totals = {
        "route": [0, 0],
        "intent": [0, 0],
        "key_entities": [0, 0],
        "clarification": [0, 0],
        "schema_validity": [0, 0],
    }
    cases = load_evaluation_cases()
    for case in cases:
        oracle_payload = {
            "reasoning": "deterministic labeled expectation replay",
            "route": case.expected_route.value,
            "intent": (
                case.expected_intent.value
                if case.expected_intent is not None
                else None
            ),
            "entities": case.expected_key_entities,
            "clarification_question": case.expected_clarification_contains,
        }
        score = score_evaluation_cases(case, oracle_payload)
        for dimension in totals:
            hits, count = getattr(score, dimension)
            totals[dimension][0] += hits
            totals[dimension][1] += count

    assert len(cases) == 26
    assert {
        "dispatch-regulation",
        "coal-quality-penalty",
        "turnaround-definition",
        "implicit-loading-count",
        "coal-stock-market",
        "freight-order-lookup",
        "ambiguous-station-followup",
        "other-business-drafting",
    } <= {case.id for case in cases}
    assert totals == {
        "route": [26, 26],
        "intent": [26, 26],
        "key_entities": [40, 40],
        "clarification": [26, 26],
        "schema_validity": [26, 26],
    }
    print("deterministic_contract_evaluator_validation cases=26 live_model=false")
    for dimension, (hits, count) in totals.items():
        print(f"{dimension}={hits}/{count}")
