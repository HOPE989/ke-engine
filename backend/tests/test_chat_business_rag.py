import pytest
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime


class RecordingRagClient:
    def __init__(self, package=None, error=None):
        self.package = package
        self.error = error
        self.calls = []

    async def retrieve_evidence(self, request):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.package


def _understanding(intent="POLICY_RULE_QA"):
    from app.domains.chat.graph.business_understanding import (
        BusinessUnderstandingResult,
    )

    return BusinessUnderstandingResult.model_validate(
        {
            "reasoning": "业务问题",
            "route": "BUSINESS",
            "intent": intent,
            "entities": {},
        }
    )


def _package(items=()):
    from app.domains.rag.services import EvidencePackage

    return EvidencePackage(
        query="集团有多少家煤炭生产企业？",
        selected_retrievers=("DOCUMENT_HYBRID",),
        evidence_items=items,
    )


@pytest.mark.asyncio
async def test_business_rag_sends_only_standalone_query_and_user_scope():
    from app.domains.chat.graph.context import ChatRuntimeContext
    from app.domains.chat.graph.nodes.business_rag import business_rag_node
    from app.domains.rag.services import EvidenceItem

    item = EvidenceItem(
        citation_id="doc-1:chunk-2",
        content="集团共有 12 家煤炭生产企业。",
        doc_id="doc-1",
        chunk_id="chunk-2",
        file_name="集团简介.md",
        rerank_score=0.9,
    )
    client = RecordingRagClient(_package((item,)))

    update = await business_rag_node(
        {
            "messages": [HumanMessage(content="有多少家？")],
            "standalone_query": "集团有多少家煤炭生产企业？",
            "business_understanding": _understanding("BUSINESS_DATA_QUERY"),
        },
        Runtime(
            context=ChatRuntimeContext(
                model=object(),
                rag_client=client,
                user_id="alice",
            )
        ),
    )

    request = client.calls[0]
    assert request.model_dump(by_alias=True) == {
        "query": "集团有多少家煤炭生产企业？",
        "accessibleBy": ("alice",),
        "docIds": (),
    }
    assert update["evidence_package"]["selectedRetrievers"] == [
        "DOCUMENT_HYBRID"
    ]
    assert update["rag_references"][0]["sourceType"] == "DOCUMENT"


@pytest.mark.asyncio
async def test_business_rag_propagates_client_failure_without_fallback():
    from app.domains.chat.graph.context import ChatRuntimeContext
    from app.domains.chat.graph.nodes.business_rag import business_rag_node

    client = RecordingRagClient(error=RuntimeError("MCP failed"))
    with pytest.raises(RuntimeError, match="MCP failed"):
        await business_rag_node(
            {
                "messages": [HumanMessage(content="当前问题")],
                "standalone_query": "完整问题",
                "business_understanding": _understanding(),
            },
            Runtime(
                context=ChatRuntimeContext(
                    model=object(),
                    rag_client=client,
                    user_id="alice",
                )
            ),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent",
    [
        "POLICY_RULE_QA",
        "TRANSPORT_OPERATION_QA",
        "COAL_SALES_QA",
        "PROFESSIONAL_KNOWLEDGE_QA",
        "BUSINESS_DATA_QUERY",
        "OTHER_BUSINESS",
    ],
)
async def test_all_business_intents_enter_same_rag_path(intent):
    from app.domains.chat.graph.nodes.business_understanding import (
        invoke_business_understanding,
    )
    from chat_graph_test_support import FakeSequentialChatModel

    command = await invoke_business_understanding(
        {"messages": [HumanMessage(content="业务问题")]},
        model=FakeSequentialChatModel([_understanding(intent)]),
    )

    assert command.goto == "contextualize_query"
