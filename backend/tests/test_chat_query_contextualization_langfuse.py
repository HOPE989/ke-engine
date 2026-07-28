from app.domains.chat.graph.query_contextualization.evaluation import (
    load_query_context_evaluation_cases,
)
from app.evaluation.chat_query_contextualization import (
    DATASET_NAME,
    dataset_item_id,
    dataset_item_payload,
    langfuse_evaluator,
)


def test_contextualization_dataset_mapping_is_stable():
    case = load_query_context_evaluation_cases()[0]

    assert DATASET_NAME.startswith("ke-engine/chat-")
    assert dataset_item_id(case) == dataset_item_id(case)
    payload = dataset_item_payload(case)
    assert payload["input"] == case.request.model_dump(mode="json")
    assert payload["metadata"]["case_id"] == case.id


def test_contextualization_langfuse_evaluator_uses_contract_score():
    evaluations = langfuse_evaluator(
        output={"standalone_query": "完整的问题"}
    )

    assert len(evaluations) == 1
    assert evaluations[0].name == "output_contract"
    assert evaluations[0].value == 1
