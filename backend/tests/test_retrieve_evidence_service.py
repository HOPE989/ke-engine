import pytest


class FakeCompiledGraph:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def ainvoke(self, graph_input):
        self.calls.append(graph_input)
        if self.error is not None:
            raise self.error
        return self.result


def _request():
    from app.domains.rag.services import RetrieveEvidenceRequest

    return RetrieveEvidenceRequest.model_validate(
        {
            "query": "付款周期？",
            "accessibleBy": ["mock-user"],
            "docIds": ["doc-1"],
            "conversationContext": [
                {"role": "assistant", "content": "正在讨论合同。"}
            ],
            "businessIntent": "COAL_SALES_QA",
        }
    )


def _outcome(status, candidates=()):
    return {
        "retrieverId": "DOCUMENT_HYBRID",
        "status": status,
        "candidates": list(candidates),
        "diagnostics": {
            "durationMs": 4,
            "resultCount": len(candidates),
            "stages": {"secretProviderPayload": "internal-only"},
        },
    }


@pytest.mark.asyncio
async def test_retrieve_evidence_projects_success_in_reranked_order():
    from app.domains.rag.services import RetrieveEvidenceService

    graph = FakeCompiledGraph(
        {
            "standalone_query": "煤炭销售合同付款周期",
            "retrieval_plan": {"internal": True},
            "retrieval_outcomes": {
                "DOCUMENT_HYBRID": _outcome(
                    "SUCCESS",
                    (
                        {
                            "chunkId": "chunk-2",
                            "docId": "doc-1",
                            "text": "付款周期为三十天。",
                            "rerankScore": 0.96,
                            "sourceMetadata": {
                                "fileName": "合同.md",
                                "url": "https://example.test/contract",
                            },
                        },
                        {
                            "chunkId": "chunk-1",
                            "docId": "doc-2",
                            "text": "逾期需要审批。",
                            "sourceMetadata": {},
                        },
                    ),
                )
            },
        }
    )

    package = await RetrieveEvidenceService(graph).retrieve_evidence(
        _request()
    )

    assert [item.citation_id for item in package.evidence_items] == [
        "doc-1:chunk-2",
        "doc-2:chunk-1",
    ]
    assert package.evidence_items[0].file_name == "合同.md"
    assert package.model_dump(mode="json", by_alias=True)[
        "evidenceItems"
    ][0]["content"] == "付款周期为三十天。"
    assert graph.calls == [
        {
            "original_query": "付款周期？",
            "conversation_context": [
                {"role": "assistant", "content": "正在讨论合同。"}
            ],
            "business_context": {"intent": "COAL_SALES_QA"},
            "document_retrieval_scope": {
                "accessibleBy": ["mock-user"],
                "docIds": ["doc-1"],
            },
        }
    ]


@pytest.mark.asyncio
async def test_retrieve_evidence_returns_empty_package_for_empty_outcome():
    from app.domains.rag.services import RetrieveEvidenceService

    graph = FakeCompiledGraph(
        {
            "standalone_query": "没有匹配的制度",
            "retrieval_outcomes": {
                "DOCUMENT_HYBRID": _outcome("EMPTY")
            },
        }
    )

    package = await RetrieveEvidenceService(graph).retrieve_evidence(
        _request()
    )

    assert package.evidence_items == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "graph",
    [
        FakeCompiledGraph(
            {
                "standalone_query": "失败",
                "retrieval_outcomes": {
                    "DOCUMENT_HYBRID": _outcome("FAILED")
                },
            }
        ),
        FakeCompiledGraph(error=RuntimeError("provider credential leaked")),
    ],
)
async def test_retrieve_evidence_fails_without_disguising_failure(graph):
    from app.domains.rag.services import (
        EvidenceRetrievalFailed,
        RetrieveEvidenceService,
    )

    with pytest.raises(
        EvidenceRetrievalFailed,
        match="document evidence retrieval failed",
    ) as caught:
        await RetrieveEvidenceService(graph).retrieve_evidence(_request())

    assert "credential" not in str(caught.value)
