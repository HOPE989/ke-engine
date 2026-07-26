import json

import pytest
from pydantic import ValidationError


def test_document_retrieval_scope_is_normalized_immutable_and_scoped():
    from app.domains.rag.graph.retrieval import DocumentRetrievalScope

    scope = DocumentRetrievalScope.model_validate(
        {
            "accessibleBy": [" team-b ", "team-a", "team-a"],
            "docIds": [" 42 ", "7", "42"],
        }
    )

    assert scope.accessible_by == ("team-a", "team-b")
    assert scope.doc_ids == ("42", "7")
    with pytest.raises(ValidationError):
        scope.accessible_by = ("other-team",)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"accessibleBy": []},
        {"accessibleBy": ["", "  "]},
        {"accessibleBy": ["team-a"], "docIds": [""]},
    ],
)
def test_document_retrieval_scope_rejects_missing_or_blank_values(payload):
    from app.domains.rag.graph.retrieval import DocumentRetrievalScope

    with pytest.raises(ValidationError):
        DocumentRetrievalScope.model_validate(payload)


def test_retrieval_contracts_are_serializable_and_do_not_require_scores():
    from app.domains.rag.graph.query_router import RetrieverKind
    from app.domains.rag.graph.retrieval import (
        DocumentCandidate,
        RetrievalDiagnostics,
        RetrievalOutcome,
        RetrievalStatus,
    )

    outcome = RetrievalOutcome(
        retriever_id=RetrieverKind.DOCUMENT_HYBRID,
        status=RetrievalStatus.SUCCESS,
        candidates=(
            DocumentCandidate(
                chunk_id="chunk-1",
                doc_id="doc-1",
                text="合同的付款周期为三十天。",
                source_metadata={
                    "fileName": "contract.md",
                    "url": "https://files.example/contract.md",
                },
            ),
        ),
        diagnostics=RetrievalDiagnostics(duration_ms=12, result_count=1),
    )

    dumped = outcome.model_dump(mode="json", by_alias=True)

    assert dumped["retrieverId"] == "DOCUMENT_HYBRID"
    assert dumped["candidates"][0] == {
        "chunkId": "chunk-1",
        "docId": "doc-1",
        "text": "合同的付款周期为三十天。",
        "sourceMetadata": {
            "fileName": "contract.md",
            "url": "https://files.example/contract.md",
        },
    }
    assert json.loads(json.dumps(dumped, ensure_ascii=False)) == dumped


def test_retrieval_options_are_immutable_and_require_valid_budgets():
    from app.domains.rag.graph.retrieval import DocumentRetrievalOptions

    options = DocumentRetrievalOptions(
        result_limit=10,
        rank_window_size=50,
        timeout_seconds=8,
    )

    assert options.rank_constant == 60
    with pytest.raises(ValidationError):
        options.result_limit = 20
    with pytest.raises(ValidationError):
        DocumentRetrievalOptions(
            result_limit=20,
            rank_window_size=10,
            timeout_seconds=8,
        )
    with pytest.raises(ValidationError):
        DocumentRetrievalOptions(rank_constant=59)


def test_retrieval_outcome_reducer_merges_distinct_ids_deterministically():
    from app.domains.rag.graph.retrieval import merge_retrieval_outcomes

    merged = merge_retrieval_outcomes(
        {"SQL": {"status": "SUCCESS"}},
        {"DOCUMENT_HYBRID": {"status": "EMPTY"}},
    )

    assert list(merged) == ["DOCUMENT_HYBRID", "SQL"]


def test_retrieval_outcome_reducer_rejects_duplicate_retriever_id():
    from app.domains.rag.graph.retrieval import merge_retrieval_outcomes

    with pytest.raises(
        ValueError,
        match="duplicate retrieval outcome: DOCUMENT_HYBRID",
    ):
        merge_retrieval_outcomes(
            {"DOCUMENT_HYBRID": {"status": "SUCCESS"}},
            {"DOCUMENT_HYBRID": {"status": "FAILED"}},
        )
