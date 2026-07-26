"""RAG Query Router 的 Langfuse Dataset Experiment 入口。"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from functools import partial
import sys
from typing import Any
from uuid import UUID, uuid5

from langfuse import Evaluation
from langfuse.api.commons.errors import NotFoundError

from app.core.config import Settings, create_settings
from app.domains.rag.graph import build_rag_graph
from app.domains.rag.graph.query_rewrite.prompt import (
    QUERY_REWRITE_PROMPT_VERSION,
)
from app.domains.rag.graph.query_router import RetrieverKind
from app.domains.rag.graph.query_router.evaluation import (
    QueryRouterEvaluationCase,
    load_query_router_evaluation_cases,
    score_query_router_output,
)
from app.domains.rag.graph.query_router.prompt import (
    QUERY_ROUTER_PROMPT_VERSION,
)
from app.infrastructure.langfuse import (
    LangfuseResources,
    create_langfuse_resources,
)
from app.infrastructure.llm import create_chat_model


DATASET_NAME = "ke-engine/rag-query-router-v1"
DATASET_ITEM_NAMESPACE = UUID("03a8eb60-a4ba-4cce-9f6f-e003b7ea8e54")


def dataset_item_id(case: QueryRouterEvaluationCase) -> str:
    return uuid5(
        DATASET_ITEM_NAMESPACE,
        f"{DATASET_NAME}:{case.id}",
    ).hex


def dataset_item_payload(
    case: QueryRouterEvaluationCase,
) -> dict[str, Any]:
    return {
        "id": dataset_item_id(case),
        "input": case.request.model_dump(mode="json"),
        "expected_output": {
            "selected_retrievers": [
                retriever.value
                for retriever in case.expected_retrievers
            ]
        },
        "metadata": {
            "case_id": case.id,
            "category": case.category,
        },
    }


def langfuse_evaluator(
    *,
    output: Mapping[str, Any],
    expected_output: Mapping[str, Any],
    **_: Any,
) -> list[Evaluation]:
    expected = tuple(
        RetrieverKind(value)
        for value in expected_output["selected_retrievers"]
    )
    score = score_query_router_output(
        output,
        expected_retrievers=expected,
    )
    return [
        _numeric_evaluation(
            "route_output_contract",
            score.output_contract[0] / score.output_contract[1],
        ),
        _numeric_evaluation(
            "route_set_exact",
            score.exact_set_match[0] / score.exact_set_match[1],
        ),
        _numeric_evaluation(
            "over_route_count",
            len(score.over_routed),
        ),
        _numeric_evaluation(
            "under_route_count",
            len(score.under_routed),
        ),
    ]


async def run_query_router_case(
    *,
    item: Any,
    model: Any,
) -> dict[str, dict[str, object]]:
    request = dict(item.input)
    available_retrievers = tuple(
        RetrieverKind(value)
        for value in request["available_retrievers"]
    )
    graph = build_rag_graph(
        model=model,
        available_retrievers=available_retrievers,
    ).compile()
    result = await graph.ainvoke(
        {"original_query": request["standalone_query"]}
    )
    return {"retrieval_plan": result["retrieval_plan"]}


def sync_dataset(
    client: Any,
    cases: Sequence[QueryRouterEvaluationCase],
) -> Any:
    try:
        client.get_dataset(DATASET_NAME)
    except NotFoundError:
        client.create_dataset(
            name=DATASET_NAME,
            description="10 labeled RAG Query Router route-set cases",
            metadata={
                "source": "ke-engine",
                "route_scoring": "objective-set-match",
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
        cases = load_query_router_evaluation_cases()
        dataset = sync_dataset(client, cases)
        model = create_chat_model(
            settings,
            model=settings.openai_model,
            callbacks=[active_resources.handler],
        )
        result = dataset.run_experiment(
            name="rag-query-router-live-model",
            run_name=_default_run_name(),
            description=(
                "Production RAG Graph Query Router against 10 labeled cases"
            ),
            task=partial(run_query_router_case, model=model),
            evaluators=[langfuse_evaluator],
            max_concurrency=1,
            metadata={
                "model": settings.openai_model,
                "query_router_prompt_version": QUERY_ROUTER_PROMPT_VERSION,
                "query_rewrite_prompt_version": (
                    QUERY_REWRITE_PROMPT_VERSION
                ),
                "app_version": settings.app_version,
                "live_model": "true",
                "route_scoring": "objective-set-match",
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


def _numeric_evaluation(name: str, value: float | int) -> Evaluation:
    return Evaluation(
        name=name,
        value=value,
        data_type="NUMERIC",
    )


def _default_run_name() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"rag-query-router-{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
