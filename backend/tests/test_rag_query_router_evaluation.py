def test_query_router_cases_cover_all_route_combinations_and_boundaries():
    from app.domains.rag.graph.query_router.evaluation import (
        load_query_router_evaluation_cases,
    )

    cases = load_query_router_evaluation_cases()

    assert len(cases) == 10
    assert len({case.id for case in cases}) == 10
    assert {
        frozenset(["DOCUMENT_HYBRID"]),
        frozenset(["SQL"]),
        frozenset(["GRAPH"]),
        frozenset(["DOCUMENT_HYBRID", "SQL"]),
        frozenset(["DOCUMENT_HYBRID", "GRAPH"]),
        frozenset(["SQL", "GRAPH"]),
        frozenset(["DOCUMENT_HYBRID", "SQL", "GRAPH"]),
    } <= {
        frozenset(
            retriever.value for retriever in case.expected_retrievers
        )
        for case in cases
    }
    assert sum(case.category == "keyword_counterexample" for case in cases) == 2
    assert any(
        len(case.request.available_retrievers) == 1
        for case in cases
    )


def test_query_router_cases_reuse_production_input_contract():
    from app.domains.rag.graph.query_router import QueryRouterInput
    from app.domains.rag.graph.query_router.evaluation import (
        load_query_router_evaluation_cases,
    )

    cases = load_query_router_evaluation_cases()

    assert all(isinstance(case.request, QueryRouterInput) for case in cases)
    assert all(case.request.standalone_query for case in cases)
    assert all(
        set(case.expected_retrievers).issubset(
            case.request.available_retrievers
        )
        for case in cases
    )


def test_query_router_scorer_matches_sets_independently_of_order():
    from app.domains.rag.graph.query_router import RetrieverKind
    from app.domains.rag.graph.query_router.evaluation import (
        score_query_router_output,
    )

    score = score_query_router_output(
        {
            "selected_retrievers": ["SQL", "DOCUMENT_HYBRID"],
            "routing_reason": "需要两种证据",
            "decision_source": "MODEL",
        },
        expected_retrievers=(
            RetrieverKind.DOCUMENT_HYBRID,
            RetrieverKind.SQL,
        ),
    )

    assert score.output_contract == (1, 1)
    assert score.exact_set_match == (1, 1)
    assert score.over_routed == ()
    assert score.under_routed == ()


def test_query_router_scorer_reports_over_and_under_routing():
    from app.domains.rag.graph.query_router import RetrieverKind
    from app.domains.rag.graph.query_router.evaluation import (
        score_query_router_output,
    )

    over = score_query_router_output(
        {
            "selected_retrievers": [
                "DOCUMENT_HYBRID",
                "SQL",
                "GRAPH",
            ],
            "routing_reason": "选择过多",
            "decision_source": "MODEL",
        },
        expected_retrievers=(
            RetrieverKind.DOCUMENT_HYBRID,
            RetrieverKind.SQL,
        ),
    )
    under = score_query_router_output(
        {
            "selected_retrievers": ["DOCUMENT_HYBRID"],
            "routing_reason": "遗漏结构化数据",
            "decision_source": "MODEL",
        },
        expected_retrievers=(
            RetrieverKind.DOCUMENT_HYBRID,
            RetrieverKind.SQL,
        ),
    )

    assert over.exact_set_match == (0, 1)
    assert over.over_routed == (RetrieverKind.GRAPH,)
    assert over.under_routed == ()
    assert under.exact_set_match == (0, 1)
    assert under.over_routed == ()
    assert under.under_routed == (RetrieverKind.SQL,)


def test_query_router_scorer_marks_invalid_output_contract():
    from app.domains.rag.graph.query_router import RetrieverKind
    from app.domains.rag.graph.query_router.evaluation import (
        score_query_router_output,
    )

    score = score_query_router_output(
        {"selected_retrievers": ["UNKNOWN"]},
        expected_retrievers=(RetrieverKind.SQL,),
    )

    assert score.output_contract == (0, 1)
    assert score.exact_set_match == (0, 1)
    assert score.over_routed == ()
    assert score.under_routed == (RetrieverKind.SQL,)
