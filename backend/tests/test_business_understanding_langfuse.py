from types import SimpleNamespace

import pytest

from app.domains.chat.graph.business_understanding import (
    BusinessIntent,
    BusinessRoute,
    BusinessUnderstandingResult,
)
from app.domains.chat.graph.business_understanding.evaluation import (
    load_evaluation_cases,
)
from app.domains.chat.graph.business_understanding.prompt import (
    BUSINESS_UNDERSTANDING_PROMPT_VERSION,
    build_business_understanding_messages,
)
from chat_graph_test_support import FakeSequentialChatModel


def _oracle_output(case):
    return {
        "reasoning": "fixture oracle",
        "route": case.expected_route.value,
        "intent": (
            case.expected_intent.value if case.expected_intent is not None else None
        ),
        "entities": case.expected_key_entities,
        "clarification_question": case.expected_clarification_contains,
    }


def test_dataset_mapping_is_stable_and_preserves_all_case_fields():
    from app.evaluation.business_understanding_langfuse import (
        dataset_item_id,
        dataset_item_payload,
    )

    case = load_evaluation_cases()[0]

    first = dataset_item_payload(case)
    second = dataset_item_payload(case)

    assert first == second
    assert first["id"] == dataset_item_id(case)
    assert first["input"] == {"messages": case.messages}
    assert first["expected_output"] == {
        "route": case.expected_route.value,
        "intent": None,
        "key_entities": {},
        "clarification_contains": None,
    }
    assert first["metadata"] == {
        "case_id": case.id,
        "category": case.category,
        "prompt_version": BUSINESS_UNDERSTANDING_PROMPT_VERSION,
    }


def test_all_eighteen_cases_have_unique_project_level_item_ids():
    from app.evaluation.business_understanding_langfuse import dataset_item_id

    ids = [dataset_item_id(case) for case in load_evaluation_cases()]

    assert len(ids) == len(set(ids)) == 18


def test_langfuse_evaluator_returns_five_numeric_scores_from_existing_scorer():
    from app.evaluation.business_understanding_langfuse import (
        dataset_item_payload,
        langfuse_evaluator,
    )

    case = load_evaluation_cases()[2]
    payload = dataset_item_payload(case)

    evaluations = langfuse_evaluator(
        input=payload["input"],
        output=_oracle_output(case),
        expected_output=payload["expected_output"],
        metadata=payload["metadata"],
    )

    assert {evaluation.name for evaluation in evaluations} == {
        "route_accuracy",
        "intent_accuracy",
        "key_entity_recall",
        "clarification_accuracy",
        "schema_validity",
    }
    assert all(evaluation.data_type == "NUMERIC" for evaluation in evaluations)
    assert all(float(evaluation.value) == 1.0 for evaluation in evaluations)
    assert all(evaluation.comment and "/" in evaluation.comment for evaluation in evaluations)


@pytest.mark.asyncio
async def test_experiment_task_invokes_real_node_with_complete_message_history():
    from app.evaluation.business_understanding_langfuse import (
        langchain_messages,
        run_business_understanding_case,
    )

    case = next(
        case for case in load_evaluation_cases() if case.id == "actual-followup"
    )
    result = BusinessUnderstandingResult(
        reasoning="继承历史中的站点和指标",
        route=BusinessRoute.BUSINESS,
        intent=BusinessIntent.BUSINESS_DATA_QUERY,
        entities={
            "departure_station": "神木站",
            "time_range": "本月",
            "data_version": "实际版",
            "metric_name": "装车计划",
        },
    )
    model = FakeSequentialChatModel([result])
    item = SimpleNamespace(input={"messages": case.messages})

    output = await run_business_understanding_case(item=item, model=model)

    expected_messages = langchain_messages(case.messages)
    assert output == result.model_dump(mode="json")
    assert model.structured_runnable.calls == [
        build_business_understanding_messages(expected_messages)
    ]
