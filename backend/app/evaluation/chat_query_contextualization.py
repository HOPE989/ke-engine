"""Chat Query Contextualization 的 Langfuse Dataset Experiment 入口。"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from functools import partial
import sys
from typing import Any
from uuid import UUID, uuid5

from langfuse import Evaluation
from langfuse.api.commons.errors import NotFoundError

from app.core.config import Settings, create_settings
from app.domains.chat.graph.query_contextualization import (
    QueryContextInput,
    QueryContextResult,
)
from app.domains.chat.graph.query_contextualization.evaluation import (
    QueryContextEvaluationCase,
    load_query_context_evaluation_cases,
    score_query_context_output,
)
from app.domains.chat.graph.query_contextualization.prompt import (
    QUERY_CONTEXTUALIZATION_PROMPT_VERSION,
    build_query_contextualization_messages,
)
from app.infrastructure.langfuse import (
    LangfuseResources,
    create_langfuse_resources,
)
from app.infrastructure.llm import create_chat_model


DATASET_NAME = "ke-engine/chat-query-contextualization-v1"
DATASET_ITEM_NAMESPACE = UUID("90c7a3fb-7dd7-4a9f-a1f5-0d3a0ab2702e")


def dataset_item_id(case: QueryContextEvaluationCase) -> str:
    return uuid5(
        DATASET_ITEM_NAMESPACE,
        f"{DATASET_NAME}:{case.id}",
    ).hex


def dataset_item_payload(
    case: QueryContextEvaluationCase,
) -> dict[str, Any]:
    return {
        "id": dataset_item_id(case),
        "input": case.request.model_dump(mode="json"),
        "expected_output": {
            "expected_standalone_query": case.expected_standalone_query,
            "semantic_review": {
                "preserved_terms": list(case.expected_preserved_terms),
                "required_term_groups": [
                    list(group)
                    for group in case.expected_required_term_groups
                ],
                "excluded_terms": list(case.expected_excluded_terms),
            },
        },
        "metadata": {
            "case_id": case.id,
            "category": case.category,
        },
    }


def langfuse_evaluator(
    *,
    output: Mapping[str, Any],
    **_: Any,
) -> list[Evaluation]:
    score = score_query_context_output(output)
    hits, total = score.output_contract
    return [
        Evaluation(
            name="output_contract",
            value=hits / total,
            comment=f"{hits}/{total}",
            data_type="NUMERIC",
        )
    ]


async def run_query_context_case(
    *,
    item: Any,
    model: Any,
) -> dict[str, str]:
    request = load_request(item.input)
    structured_model = model.with_structured_output(
        QueryContextResult,
        method="json_mode",
    )
    result = await structured_model.ainvoke(
        build_query_contextualization_messages(request)
    )
    validated = QueryContextResult.model_validate(result)
    return {"standalone_query": validated.standalone_query}


def load_request(value: object) -> QueryContextInput:
    return QueryContextInput.model_validate(value)


def sync_dataset(
    client: Any,
    cases: Sequence[QueryContextEvaluationCase],
) -> Any:
    try:
        client.get_dataset(DATASET_NAME)
    except NotFoundError:
        client.create_dataset(
            name=DATASET_NAME,
            description="Chat query contextualization semantic review cases",
            metadata={
                "source": "ke-engine",
                "semantic_scoring": "human-or-calibrated-llm-judge",
            },
        )
    for case in cases:
        client.create_dataset_item(
            dataset_name=DATASET_NAME,
            **dataset_item_payload(case),
        )
    return client.get_dataset(DATASET_NAME)


def run_experiment(
    settings: Settings,
    *,
    resources: LangfuseResources | None = None,
) -> Any:
    active_resources = resources or create_langfuse_resources(settings)
    if active_resources is None:
        raise RuntimeError(
            "Langfuse configuration is required for the experiment"
        )
    if not settings.openai_model:
        raise RuntimeError("OPENAI_MODEL is required for the experiment")

    client = active_resources.client
    try:
        if not client.auth_check():
            raise RuntimeError("Langfuse authentication failed")
        cases = load_query_context_evaluation_cases()
        dataset = sync_dataset(client, cases)
        model = create_chat_model(
            settings,
            model=settings.openai_model,
            callbacks=[active_resources.handler],
        )
        result = dataset.run_experiment(
            name="chat-query-contextualization-live-model",
            run_name=_default_run_name(),
            description="Chat contextualization against labeled cases",
            task=partial(run_query_context_case, model=model),
            evaluators=[langfuse_evaluator],
            max_concurrency=1,
            metadata={
                "model": settings.openai_model,
                "prompt_version": QUERY_CONTEXTUALIZATION_PROMPT_VERSION,
                "app_version": settings.app_version,
                "live_model": "true",
                "semantic_scoring": "not_automated",
            },
        )
        print(result.format())
        dataset_run_url = getattr(result, "dataset_run_url", None)
        if not dataset_run_url:
            raise RuntimeError(
                "Langfuse experiment did not return a Dataset Run URL"
            )
        print(dataset_run_url)
        return result
    finally:
        client.shutdown()


def main() -> int:
    try:
        run_experiment(create_settings())
    except Exception as exc:
        print(f"Langfuse experiment failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _default_run_name() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"chat-query-contextualization-{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
