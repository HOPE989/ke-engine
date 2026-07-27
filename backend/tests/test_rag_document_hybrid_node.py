import asyncio
import json

import pytest
from pydantic import ValidationError

from rag_query_rewrite_test_support import (
    RecordingRetrieverFactory,
    document,
)


def _state(**overrides):
    state = {
        "standalone_query": "合同付款周期",
        "document_retrieval_scope": {
            "accessibleBy": ["team-a"],
            "docIds": ["doc-1"],
        },
    }
    state.update(overrides)
    return state


@pytest.mark.asyncio
async def test_document_hybrid_node_invokes_scoped_retriever_and_converts_docs():
    from app.domains.rag.graph.nodes.document_hybrid import (
        document_hybrid_node,
    )
    from app.domains.rag.graph.retrieval import DocumentRetrievalOptions

    factory = RecordingRetrieverFactory(
        [
            document(
                fileName="contract.md",
                url="https://files.example/contract.md",
                accessibleBy="team-a",
                secret="must-not-leak",
            )
        ],
        retrieval_stages={
            "BM25": {
                "resultCount": 1,
                "scoreType": "ELASTICSEARCH_BM25",
                "ranking": [
                    {
                        "rank": 1,
                        "chunkId": "chunk-1",
                        "docId": "doc-1",
                        "score": 8.5,
                        "textPreview": "合同付款周期为三十天。",
                    }
                ],
            }
        },
    )
    config = {
        "metadata": {"request_id": "request-1"},
        "callbacks": [object()],
    }

    update = await document_hybrid_node(
        _state(),
        retriever_factory=factory,
        options=DocumentRetrievalOptions(),
        config=config,
    )

    assert factory.scopes[0].accessible_by == ("team-a",)
    assert factory.scopes[0].doc_ids == ("doc-1",)
    assert factory.retrievers[0].calls == [
        ("合同付款周期", config)
    ]
    outcome = update["retrieval_outcomes"]["DOCUMENT_HYBRID"]
    assert outcome["status"] == "SUCCESS"
    assert outcome["diagnostics"]["resultCount"] == 1
    assert outcome["diagnostics"]["stages"]["BM25"]["ranking"][0] == {
        "rank": 1,
        "chunkId": "chunk-1",
        "docId": "doc-1",
        "score": 8.5,
        "textPreview": "合同付款周期为三十天。",
    }
    assert outcome["candidates"] == [
        {
            "chunkId": "chunk-1",
            "docId": "doc-1",
            "text": "合同付款周期为三十天。",
            "sourceMetadata": {
                "fileName": "contract.md",
                "url": "https://files.example/contract.md",
            },
        }
    ]
    assert "team-a" not in json.dumps(outcome, ensure_ascii=False)
    assert "must-not-leak" not in json.dumps(outcome, ensure_ascii=False)


@pytest.mark.asyncio
async def test_document_hybrid_node_returns_empty_outcome():
    from app.domains.rag.graph.nodes.document_hybrid import (
        document_hybrid_node,
    )
    from app.domains.rag.graph.retrieval import DocumentRetrievalOptions

    update = await document_hybrid_node(
        _state(),
        retriever_factory=RecordingRetrieverFactory(),
        options=DocumentRetrievalOptions(),
    )

    outcome = update["retrieval_outcomes"]["DOCUMENT_HYBRID"]
    assert outcome["status"] == "EMPTY"
    assert outcome["candidates"] == []
    assert outcome["diagnostics"]["resultCount"] == 0


@pytest.mark.asyncio
async def test_document_hybrid_node_sanitizes_dependency_failure():
    from app.domains.rag.graph.nodes.document_hybrid import (
        document_hybrid_node,
    )
    from app.domains.rag.graph.retrieval import DocumentRetrievalOptions

    update = await document_hybrid_node(
        _state(),
        retriever_factory=RecordingRetrieverFactory(
            error=OSError(
                "http://elastic:9200?api_key=secret failed"
            )
        ),
        options=DocumentRetrievalOptions(),
    )

    outcome = update["retrieval_outcomes"]["DOCUMENT_HYBRID"]
    assert outcome["status"] == "FAILED"
    assert outcome["candidates"] == []
    assert "elastic" not in json.dumps(outcome)
    assert "secret" not in json.dumps(outcome)


@pytest.mark.asyncio
async def test_document_hybrid_node_applies_request_timeout():
    from app.domains.rag.graph.nodes.document_hybrid import (
        document_hybrid_node,
    )
    from app.domains.rag.graph.retrieval import DocumentRetrievalOptions

    class SlowRetriever:
        async def ainvoke(self, query, config=None):
            await asyncio.sleep(1)

    class SlowFactory:
        def create(self, scope):
            return SlowRetriever()

    update = await document_hybrid_node(
        _state(),
        retriever_factory=SlowFactory(),
        options=DocumentRetrievalOptions(timeout_seconds=0.001),
    )

    assert (
        update["retrieval_outcomes"]["DOCUMENT_HYBRID"]["status"]
        == "FAILED"
    )


@pytest.mark.asyncio
async def test_document_hybrid_node_propagates_cancellation():
    from app.domains.rag.graph.nodes.document_hybrid import (
        document_hybrid_node,
    )
    from app.domains.rag.graph.retrieval import DocumentRetrievalOptions

    with pytest.raises(asyncio.CancelledError):
        await document_hybrid_node(
            _state(),
            retriever_factory=RecordingRetrieverFactory(
                error=asyncio.CancelledError()
            ),
            options=DocumentRetrievalOptions(),
        )


@pytest.mark.asyncio
async def test_document_hybrid_node_rejects_scope_before_factory_call():
    from app.domains.rag.graph.nodes.document_hybrid import (
        document_hybrid_node,
    )
    from app.domains.rag.graph.retrieval import DocumentRetrievalOptions

    factory = RecordingRetrieverFactory()

    with pytest.raises(ValidationError):
        await document_hybrid_node(
            _state(document_retrieval_scope={"accessibleBy": []}),
            retriever_factory=factory,
            options=DocumentRetrievalOptions(),
        )

    assert factory.scopes == []


def test_collector_requires_every_selected_retriever_outcome():
    from app.domains.rag.graph.nodes.collect_retrieval_outcomes import (
        MissingRetrievalOutcome,
        collect_retrieval_outcomes_node,
    )

    with pytest.raises(
        MissingRetrievalOutcome,
        match="DOCUMENT_HYBRID",
    ):
        collect_retrieval_outcomes_node(
            {
                "retrieval_plan": {
                    "selected_retrievers": ["DOCUMENT_HYBRID"],
                    "routing_reason": "需要文档",
                    "decision_source": "MODEL",
                },
                "retrieval_outcomes": {},
            }
        )


def test_collector_accepts_complete_outcomes():
    from app.domains.rag.graph.nodes.collect_retrieval_outcomes import (
        collect_retrieval_outcomes_node,
    )

    assert (
        collect_retrieval_outcomes_node(
            {
                "retrieval_plan": {
                    "selected_retrievers": ["DOCUMENT_HYBRID"],
                    "routing_reason": "需要文档",
                    "decision_source": "MODEL",
                },
                "retrieval_outcomes": {
                    "DOCUMENT_HYBRID": {"status": "EMPTY"}
                },
            }
        )
        == {}
    )
