from typing import Any

from langchain_core.language_models.fake_chat_models import (
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
import pytest

from app.domains.chat.services.conversation import AcceptedUserTurn


class StructuredRunnable:
    def __init__(self, result):
        self.result = result

    async def ainvoke(self, messages):
        return self.result


class BusinessAndAnswerModel(GenericFakeChatModel):
    structured_result: Any

    def with_structured_output(self, schema, **kwargs):
        return StructuredRunnable(self.structured_result)


class RecordingRagClient:
    def __init__(self, package):
        self.package = package
        self.calls = []

    async def retrieve_evidence(self, request):
        self.calls.append(request)
        return self.package


class Publisher:
    def __init__(self):
        self.events = []

    async def publish(self, event, payload):
        self.events.append((event, payload))


class Transaction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return None


class Session:
    def __init__(self):
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def begin(self):
        return Transaction()

    def add(self, value):
        self.added.append(value)


class IdGenerator:
    def next_id(self):
        return 3001


@pytest.mark.asyncio
async def test_chat_rag_vertical_calls_client_answers_streams_and_persists():
    from app.domains.chat.graph import build_chat_graph
    from app.domains.chat.graph.business_understanding import (
        BusinessUnderstandingResult,
    )
    from app.domains.chat.services.runtime import CompletionProducer
    from app.domains.rag.services import EvidenceItem, EvidencePackage

    classification = BusinessUnderstandingResult.model_validate(
        {
            "reasoning": "制度文档问答",
            "route": "BUSINESS",
            "intent": "POLICY_RULE_QA",
            "entities": {},
        }
    )
    model = BusinessAndAnswerModel(
        messages=iter([AIMessage(content="应按调度规程执行。[1]")]),
        structured_result=classification,
    )
    package = EvidencePackage(
        query="超限货物列车如何编组？",
        standalone_query="超限货物列车编组要求",
        evidence_items=(
            EvidenceItem(
                citation_id="doc-1:chunk-1",
                content="超限货物列车应按调度规程编组。",
                doc_id="doc-1",
                chunk_id="chunk-1",
                file_name="调度规程.md",
                rerank_score=0.95,
            ),
        ),
    )
    rag_client = RecordingRagClient(package)
    publisher = Publisher()
    session = Session()
    graph = build_chat_graph().compile(checkpointer=InMemorySaver())
    producer = CompletionProducer(
        graph=graph,
        model=model,
        rag_client=rag_client,
        session_factory=lambda: session,
        id_generator=IdGenerator(),
        publisher=publisher,
    )

    await producer.run(
        turn=AcceptedUserTurn(
            conversation_id=1001,
            user_message_id=2001,
            content="超限货物列车如何编组？",
        ),
        user_id="mock-user",
    )

    assert len(rag_client.calls) == 1
    assert rag_client.calls[0].accessible_by == ("mock-user",)
    assert rag_client.calls[0].business_intent == "POLICY_RULE_QA"
    assert publisher.events[-1][0] == "completed"
    deltas = [
        payload.content
        for event, payload in publisher.events
        if event == "content_delta"
    ]
    assert "".join(deltas) == "应按调度规程执行。[1]"
    assistant = session.added[0]
    assert assistant.content == "应按调度规程执行。[1]"
    assert assistant.rag_references == [
        {
            "citationId": "doc-1:chunk-1",
            "docId": "doc-1",
            "chunkId": "chunk-1",
            "fileName": "调度规程.md",
            "rerankScore": 0.95,
        }
    ]
