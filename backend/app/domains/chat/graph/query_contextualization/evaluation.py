"""Chat Query Contextualization 的本地评测样例与客观输出契约。"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.domains.chat.graph.query_contextualization.models import (
    QueryContextInput,
    QueryContextResult,
)


@dataclass(frozen=True)
class QueryContextEvaluationCase:
    id: str
    category: str
    request: QueryContextInput
    expected_standalone_query: str
    expected_preserved_terms: tuple[str, ...]
    expected_required_term_groups: tuple[tuple[str, ...], ...]
    expected_excluded_terms: tuple[str, ...]


@dataclass(frozen=True)
class QueryContextContractScore:
    output_contract: tuple[int, int]


def load_query_context_evaluation_cases() -> list[QueryContextEvaluationCase]:
    fixture_path = (
        Path(__file__).resolve().parents[5]
        / "tests"
        / "fixtures"
        / "query_contextualization_cases.json"
    )
    raw_cases = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [
        QueryContextEvaluationCase(
            id=case["id"],
            category=case["category"],
            request=QueryContextInput.model_validate(
                {
                    "original_query": case["original_query"],
                    "conversation_context": case["conversation_context"],
                    "business_context": case["business_context"],
                }
            ),
            expected_standalone_query=case["expected_standalone_query"],
            expected_preserved_terms=tuple(case["expected_preserved_terms"]),
            expected_required_term_groups=tuple(
                tuple(group)
                for group in case["expected_required_term_groups"]
            ),
            expected_excluded_terms=tuple(case["expected_excluded_terms"]),
        )
        for case in raw_cases
    ]


def score_query_context_output(
    actual: Mapping[str, Any] | QueryContextResult,
) -> QueryContextContractScore:
    actual_payload = (
        actual.model_dump(mode="json")
        if isinstance(actual, QueryContextResult)
        else dict(actual)
    )
    try:
        QueryContextResult.model_validate(actual_payload)
        output_valid = True
    except ValidationError:
        output_valid = False
    return QueryContextContractScore(
        output_contract=(int(output_valid), 1)
    )
