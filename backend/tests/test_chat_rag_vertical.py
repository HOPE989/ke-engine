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

    async def ainvoke(self, messages, config=None):
        return self.result


class BusinessAndAnswerModel(GenericFakeChatModel):
    structured_results: Any

    def with_structured_output(self, schema, **kwargs):
        return StructuredRunnable(next(self.structured_results))


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
    from app.domains.chat.graph.query_contextualization import (
        QueryContextResult,
    )
    from app.domains.chat.services.runtime import CompletionProducer
    from app.domains.rag.services import EvidenceItem, EvidencePackage

    classification = BusinessUnderstandingResult.model_validate(
        {
            "reasoning": "业务数据问题，但答案存在文档知识中",
            "route": "BUSINESS",
            "intent": "BUSINESS_DATA_QUERY",
            "entities": {},
        }
    )
    model = BusinessAndAnswerModel(
        messages=iter([AIMessage(content="集团共有 12 家煤炭生产企业。[1]")]),
        structured_results=iter(
            [
                classification,
                QueryContextResult(
                    standalone_query="集团有多少家煤炭生产企业？"
                ),
            ]
        ),
    )
    package = EvidencePackage(
        query="集团有多少家煤炭生产企业？",
        selected_retrievers=("DOCUMENT_HYBRID",),
        evidence_items=(
            EvidenceItem(
                citation_id="doc-1:chunk-1",
                content="集团共有 12 家煤炭生产企业。",
                doc_id="doc-1",
                chunk_id="chunk-1",
                file_name="集团简介.md",
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
            content="集团有多少家煤炭生产企业？",
        ),
        user_id="mock-user",
    )

    assert len(rag_client.calls) == 1
    assert rag_client.calls[0].accessible_by == ("mock-user",)
    assert rag_client.calls[0].query == "集团有多少家煤炭生产企业？"
    assert publisher.events[-1][0] == "completed"
    deltas = [
        payload.content
        for event, payload in publisher.events
        if event == "content_delta"
    ]
    assert "".join(deltas) == "集团共有 12 家煤炭生产企业。[1]"
    trace_steps = [
        (payload.node, payload.status)
        for event, payload in publisher.events
        if event == "trace_step"
    ]
    assert len(trace_steps) == len(set(trace_steps))
    assert [event for event, _ in publisher.events].count("rag_evidence") == 1
    assistant = session.added[0]
    assert assistant.content == "集团共有 12 家煤炭生产企业。[1]"
    assert assistant.rag_references == [
        {
            "sourceType": "DOCUMENT",
            "citationId": "doc-1:chunk-1",
            "docId": "doc-1",
            "chunkId": "chunk-1",
            "fileName": "集团简介.md",
            "rerankScore": 0.95,
        }
    ]
