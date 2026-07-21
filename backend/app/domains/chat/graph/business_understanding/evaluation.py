import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import (
    BusinessIntent,
    BusinessRoute,
    BusinessUnderstandingResult,
)


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    category: str
    messages: list[dict[str, str]]
    expected_route: BusinessRoute
    expected_intent: BusinessIntent | None
    expected_key_entities: dict[str, str]
    expected_clarification_contains: str | None


@dataclass(frozen=True)
class EvaluationScore:
    route: tuple[int, int]
    intent: tuple[int, int]
    key_entities: tuple[int, int]
    clarification: tuple[int, int]
    schema_validity: tuple[int, int]


def load_evaluation_cases() -> list[EvaluationCase]:
    fixture_path = (
        Path(__file__).resolve().parents[5]
        / "tests"
        / "fixtures"
        / "business_understanding_cases.json"
    )
    raw_cases = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [
        EvaluationCase(
            id=case["id"],
            category=case["category"],
            messages=case["messages"],
            expected_route=BusinessRoute(case["expected_route"]),
            expected_intent=(
                BusinessIntent(case["expected_intent"])
                if case["expected_intent"] is not None
                else None
            ),
            expected_key_entities=case["expected_key_entities"],
            expected_clarification_contains=case["expected_clarification_contains"],
        )
        for case in raw_cases
    ]


def score_evaluation_cases(
    expected: EvaluationCase,
    actual: Mapping[str, Any] | BusinessUnderstandingResult,
) -> EvaluationScore:
    actual_payload = (
        actual.model_dump(mode="json")
        if isinstance(actual, BusinessUnderstandingResult)
        else dict(actual)
    )
    actual_entities = actual_payload.get("entities")
    if not isinstance(actual_entities, Mapping):
        actual_entities = {}

    entity_hits = sum(
        actual_entities.get(key) == value
        for key, value in expected.expected_key_entities.items()
    )
    expected_question = expected.expected_clarification_contains
    actual_question = actual_payload.get("clarification_question")
    clarification_matches = (
        actual_question is None
        if expected_question is None
        else isinstance(actual_question, str) and expected_question in actual_question
    )

    try:
        BusinessUnderstandingResult.model_validate(actual_payload)
        schema_valid = True
    except ValidationError:
        schema_valid = False

    return EvaluationScore(
        route=(int(actual_payload.get("route") == expected.expected_route), 1),
        intent=(int(actual_payload.get("intent") == expected.expected_intent), 1),
        key_entities=(entity_hits, len(expected.expected_key_entities)),
        clarification=(int(clarification_matches), 1),
        schema_validity=(int(schema_valid), 1),
    )
