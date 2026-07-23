from dataclasses import replace


def test_query_rewrite_evaluation_cases_cover_high_risk_categories():
    from app.domains.rag.graph.query_rewrite.evaluation import (
        load_query_rewrite_evaluation_cases,
    )

    cases = load_query_rewrite_evaluation_cases()

    assert len(cases) == 28
    assert len({case.id for case in cases}) == 28
    assert {
        "multi_turn_ellipsis",
        "current_query_precedence",
        "time_range_preservation",
        "numeric_range_preservation",
        "negation_preservation",
        "comparison_preservation",
        "ownership_preservation",
        "identifier_integrity",
        "no_invention",
        "terminology_normalization",
        "conversational_noise",
        "standalone_stability",
        "single_query_boundary",
    } == {case.category for case in cases}
    assert all(case.expected_standalone_query.strip() for case in cases)
    assert all(
        case.expected_preserved_terms
        or case.expected_required_term_groups
        or case.expected_excluded_terms
        for case in cases
    )


def test_query_rewrite_evaluation_cases_reuse_production_input_contract():
    from app.domains.rag.graph.query_rewrite import QueryRewriteInput
    from app.domains.rag.graph.query_rewrite.evaluation import (
        load_query_rewrite_evaluation_cases,
    )

    cases = load_query_rewrite_evaluation_cases()
    multi_turn_case = next(
        case
        for case in cases
        if case.id == "followup-resolve-document-reference"
    )

    assert isinstance(multi_turn_case.request, QueryRewriteInput)
    assert multi_turn_case.request.original_query
    assert multi_turn_case.request.conversation_context


def test_objective_scorer_checks_only_the_output_contract():
    from app.domains.rag.graph.query_rewrite.evaluation import (
        load_query_rewrite_evaluation_cases,
        score_query_rewrite_output,
    )

    case = load_query_rewrite_evaluation_cases()[0]
    unrelated_reference = replace(
        case,
        expected_standalone_query="一个完全不同的人工参考答案",
        expected_preserved_terms=("不会用于代码评分",),
        expected_required_term_groups=(("同样不会用于代码评分",),),
        expected_excluded_terms=("也不会用于代码评分",),
    )

    assert score_query_rewrite_output(
        {"standalone_query": "任意非空单查询"}
    ) == score_query_rewrite_output(
        {"standalone_query": unrelated_reference.expected_standalone_query}
    )
    assert score_query_rewrite_output(
        {"standalone_query": "任意非空单查询"}
    ).output_contract == (1, 1)
    assert score_query_rewrite_output(
        {"standalone_query": "   "}
    ).output_contract == (0, 1)
    assert score_query_rewrite_output(
        {
            "standalone_query": "查询运单",
            "query_variants": ["查询运单", "搜索运单"],
        }
    ).output_contract == (0, 1)
