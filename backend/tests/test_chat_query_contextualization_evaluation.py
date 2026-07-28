from dataclasses import replace

from app.domains.chat.graph.query_contextualization import QueryContextInput
from app.domains.chat.graph.query_contextualization.evaluation import (
    load_query_context_evaluation_cases,
    score_query_context_output,
)


def test_query_context_evaluation_cases_cover_high_risk_categories():
    cases = load_query_context_evaluation_cases()

    assert len(cases) == 28
    assert len({case.id for case in cases}) == 28
    assert isinstance(cases[0].request, QueryContextInput)
    assert any(case.request.conversation_context for case in cases)


def test_query_context_scorer_checks_only_output_contract():
    case = load_query_context_evaluation_cases()[0]
    unrelated = replace(case, expected_standalone_query="另一个人工参考答案")

    assert score_query_context_output(
        {"standalone_query": "任意非空单查询"}
    ) == score_query_context_output(
        {"standalone_query": unrelated.expected_standalone_query}
    )
    assert score_query_context_output(
        {"standalone_query": "查"}
    ).output_contract == (0, 1)
