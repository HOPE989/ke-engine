"""Query Router 的仓库评测样例与客观集合评分。"""

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.domains.rag.graph.query_router.models import (
    QueryRouterInput,
    RetrievalPlan,
    RetrieverKind,
)


@dataclass(frozen=True)
class QueryRouterEvaluationCase:
    id: str
    category: str
    request: QueryRouterInput
    expected_retrievers: tuple[RetrieverKind, ...]


@dataclass(frozen=True)
class QueryRouterSetScore:
    output_contract: tuple[int, int]
    exact_set_match: tuple[int, int]
    over_routed: tuple[RetrieverKind, ...]
    under_routed: tuple[RetrieverKind, ...]


def load_query_router_evaluation_cases() -> list[QueryRouterEvaluationCase]:
    fixture_path = (
        Path(__file__).resolve().parents[5]
        / "tests"
        / "fixtures"
        / "query_router_cases.json"
    )
    raw_cases = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [
        QueryRouterEvaluationCase(
            id=case["id"],
            category=case["category"],
            request=QueryRouterInput.model_validate(
                {
                    "standalone_query": case["standalone_query"],
                    "available_retrievers": case["available_retrievers"],
                }
            ),
            expected_retrievers=tuple(
                RetrieverKind(value)
                for value in case["expected_retrievers"]
            ),
        )
        for case in raw_cases
    ]


def score_query_router_output(
    actual: Mapping[str, Any] | RetrievalPlan,
    *,
    expected_retrievers: Collection[RetrieverKind],
) -> QueryRouterSetScore:
    actual_payload: Mapping[str, Any] | RetrievalPlan = actual
    if (
        isinstance(actual_payload, Mapping)
        and "retrieval_plan" in actual_payload
    ):
        actual_payload = actual_payload["retrieval_plan"]

    try:
        plan = (
            actual_payload
            if isinstance(actual_payload, RetrievalPlan)
            else RetrievalPlan.model_validate(actual_payload)
        )
        actual_set = set(plan.selected_retrievers)
        output_valid = True
    except (TypeError, ValidationError):
        actual_set = set()
        output_valid = False

    expected_set = {
        RetrieverKind(retriever) for retriever in expected_retrievers
    }
    over_routed = tuple(
        retriever
        for retriever in RetrieverKind
        if retriever in actual_set - expected_set
    )
    under_routed = tuple(
        retriever
        for retriever in RetrieverKind
        if retriever in expected_set - actual_set
    )
    return QueryRouterSetScore(
        output_contract=(int(output_valid), 1),
        exact_set_match=(
            int(output_valid and actual_set == expected_set),
            1,
        ),
        over_routed=over_routed,
        under_routed=under_routed,
    )
