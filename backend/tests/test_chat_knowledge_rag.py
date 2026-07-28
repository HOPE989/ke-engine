import pytest
from langchain_core.messages import AIMessage, HumanMessage
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
            "reasoning": "文档知识问题",
            "route": "BUSINESS",
            "intent": intent,
            "entities": {},
        }
    )


def _package(items=()):
    from app.domains.rag.services import EvidencePackage

    return EvidencePackage(
        query="当前问题",
        standalone_query="完整问题",
        evidence_items=items,
    )


@pytest.mark.asyncio
async def test_knowledge_rag_sends_current_query_ten_history_and_user_scope():
    from app.domains.chat.graph.context import ChatRuntimeContext
    from app.domains.chat.graph.nodes.knowledge_rag import knowledge_rag_node
    from app.domains.rag.services import EvidenceItem

    history = [
        (
            HumanMessage(content=f"用户历史 {index}")
            if index % 2 == 0
            else AIMessage(content=f"助手历史 {index}")
        )
        for index in range(12)
    ]
    item = EvidenceItem(
        citation_id="doc-1:chunk-2",
        content="规则正文",
        doc_id="doc-1",
        chunk_id="chunk-2",
        file_name="规程.md",
        rerank_score=0.9,
    )
    client = RecordingRagClient(_package((item,)))

    update = await knowledge_rag_node(
        {
            "messages": [*history, HumanMessage(content="当前问题")],
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

    request = client.calls[0]
    assert request.query == "当前问题"
    assert request.accessible_by == ("alice",)
    assert request.business_intent == "POLICY_RULE_QA"
    assert len(request.conversation_context) == 10
    assert request.conversation_context[0].content == "用户历史 2"
    assert update["evidence_package"]["standaloneQuery"] == "完整问题"
    assert update["rag_references"] == [
        {
            "citationId": "doc-1:chunk-2",
            "docId": "doc-1",
            "chunkId": "chunk-2",
            "fileName": "规程.md",
            "rerankScore": 0.9,
        }
    ]


@pytest.mark.asyncio
async def test_knowledge_rag_propagates_client_failure_without_fallback():
    from app.domains.chat.graph.context import ChatRuntimeContext
    from app.domains.chat.graph.nodes.knowledge_rag import knowledge_rag_node

    client = RecordingRagClient(error=RuntimeError("MCP failed"))

    with pytest.raises(RuntimeError, match="MCP failed"):
        await knowledge_rag_node(
            {
                "messages": [HumanMessage(content="当前问题")],
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

    assert len(client.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "target"),
    [
        ("POLICY_RULE_QA", "knowledge_rag"),
        ("TRANSPORT_OPERATION_QA", "knowledge_rag"),
        ("COAL_SALES_QA", "knowledge_rag"),
        ("PROFESSIONAL_KNOWLEDGE_QA", "knowledge_rag"),
        ("BUSINESS_DATA_QUERY", "business_boundary"),
        ("OTHER_BUSINESS", "business_boundary"),
    ],
)
async def test_business_intent_routes_to_document_rag_or_boundary(
    intent,
    target,
):
    from app.domains.chat.graph.nodes.business_understanding import (
        invoke_business_understanding,
    )
    from chat_graph_test_support import FakeSequentialChatModel

    result = _understanding(intent)
    model = FakeSequentialChatModel([result])

    command = await invoke_business_understanding(
        {"messages": [HumanMessage(content="业务问题")]},
        model=model,
    )

    assert command.goto == target
