"""Query Rewrite 的本地评测样例与客观输出契约。"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.domains.rag.graph.query_rewrite.models import (
    QueryRewriteInput,
    QueryRewriteResult,
)


@dataclass(frozen=True)
class QueryRewriteEvaluationCase:
    """保留人工语义评审信息，但不将其用于代码自动打分。"""

    id: str
    category: str
    request: QueryRewriteInput
    expected_standalone_query: str
    expected_preserved_terms: tuple[str, ...]
    expected_required_term_groups: tuple[tuple[str, ...], ...]
    expected_excluded_terms: tuple[str, ...]


@dataclass(frozen=True)
class QueryRewriteContractScore:
    output_contract: tuple[int, int]


def load_query_rewrite_evaluation_cases() -> list[QueryRewriteEvaluationCase]:
    fixture_path = (
        Path(__file__).resolve().parents[5]
        / "tests"
        / "fixtures"
        / "query_rewrite_cases.json"
    )
    raw_cases = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [
        QueryRewriteEvaluationCase(
            id=case["id"],
            category=case["category"],
            request=QueryRewriteInput.model_validate(
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


def score_query_rewrite_output(
    actual: Mapping[str, Any] | QueryRewriteResult,
) -> QueryRewriteContractScore:
    """只验证可客观确定的单字段输出形状，不判断语义质量。"""

    actual_payload = (
        actual.model_dump(mode="json")
        if isinstance(actual, QueryRewriteResult)
        else dict(actual)
    )
    try:
        QueryRewriteResult.model_validate(actual_payload)
        output_valid = True
    except ValidationError:
        output_valid = False
    return QueryRewriteContractScore(
        output_contract=(int(output_valid), 1)
    )
