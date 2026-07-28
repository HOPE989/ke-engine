from langchain_core.messages import AIMessageChunk
from langgraph.types import StateSnapshot
import pytest

from app.domains.chat.services.conversation import AcceptedUserTurn


class GroundedGraph:
    def __init__(self):
        self.state_reads = 0
        self.context = None

    async def aget_state(self, config):
        self.state_reads += 1
        values = (
            {}
            if self.state_reads == 1
            else {
                "rag_references": [
                    {
                        "citationId": "doc-1:chunk-1",
                        "docId": "doc-1",
                        "chunkId": "chunk-1",
                        "fileName": "规程.md",
                        "rerankScore": 0.93,
                    }
                ]
            }
        )
        return StateSnapshot(
            values=values,
            next=(),
            config=config,
            metadata=None,
            created_at=None,
            parent_config=None,
            tasks=(),
            interrupts=(),
        )

    async def astream_events(
        self,
        graph_input,
        config,
        *,
        context,
        version,
    ):
        self.context = context
        for content in ("依据", "。[1]"):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": AIMessageChunk(content=content)},
                "metadata": {"langgraph_node": "grounded_answer"},
            }


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
async def test_grounded_completion_streams_and_persists_final_references():
    from app.domains.chat.services.runtime import CompletionProducer

    graph = GroundedGraph()
    publisher = Publisher()
    session = Session()
    rag_client = object()
    producer = CompletionProducer(
        graph=graph,
        model=object(),
        rag_client=rag_client,
        session_factory=lambda: session,
        id_generator=IdGenerator(),
        publisher=publisher,
    )

    await producer.run(
        turn=AcceptedUserTurn(1001, 2001, "规程要求？"),
        user_id="alice",
    )

    assert [event for event, _ in publisher.events] == [
        "metadata",
        "content_delta",
        "content_delta",
        "completed",
    ]
    assert graph.state_reads == 2
    assert graph.context.rag_client is rag_client
    assert graph.context.user_id == "alice"
    assistant = session.added[0]
    assert assistant.content == "依据。[1]"
    assert assistant.rag_references == [
        {
            "citationId": "doc-1:chunk-1",
            "docId": "doc-1",
            "chunkId": "chunk-1",
            "fileName": "规程.md",
            "rerankScore": 0.93,
        }
    ]
