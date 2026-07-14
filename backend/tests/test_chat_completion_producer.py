from langchain_core.messages import AIMessageChunk, HumanMessage
import pytest

from app.domains.chat.services.conversation import AcceptedUserTurn


class FakeGraph:
    def __init__(self, calls, publisher):
        self.calls = calls
        self.publisher = publisher
        self.invocations = []

    async def astream_events(self, graph_input, config, *, context, version):
        assert self.publisher.events[0][0] == "metadata"
        self.invocations.append(
            {
                "input": graph_input,
                "config": config,
                "context": context,
                "version": version,
            }
        )
        self.calls.append("graph_start")
        for content in ["你", "好"]:
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": AIMessageChunk(content=content)},
            }


class FakePublisher:
    def __init__(self, calls):
        self.calls = calls
        self.events = []

    async def publish(self, event, payload):
        if event == "completed":
            assert "assistant_commit" in self.calls
        self.calls.append(f"publish_{event}")
        self.events.append((event, payload))


class FakeTransaction:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.session.calls.append("assistant_commit")


class FakeSession:
    def __init__(self, calls):
        self.calls = calls
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def begin(self):
        return FakeTransaction(self)

    def add(self, value):
        self.added.append(value)


class FakeSessionFactory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self.session


class FakeIdGenerator:
    def next_id(self):
        return 3001


@pytest.mark.asyncio
async def test_completion_producer_success_persists_before_completed_and_preserves_deltas():
    from app.domains.chat.services.runtime import CompletionProducer

    calls = []
    publisher = FakePublisher(calls)
    graph = FakeGraph(calls, publisher)
    session = FakeSession(calls)
    model = object()
    producer = CompletionProducer(
        graph=graph,
        model=model,
        session_factory=FakeSessionFactory(session),
        id_generator=FakeIdGenerator(),
        publisher=publisher,
    )
    turn = AcceptedUserTurn(
        conversation_id=1001,
        user_message_id=2001,
        content="hello",
    )

    await producer.run(turn=turn, user_id="alice")

    assert [event for event, _ in publisher.events] == [
        "metadata",
        "content_delta",
        "content_delta",
        "completed",
    ]
    assert [payload.content for event, payload in publisher.events if event == "content_delta"] == [
        "你",
        "好",
    ]
    invocation = graph.invocations[0]
    assert invocation["input"] == {"messages": [HumanMessage(content="hello")]}
    assert invocation["config"] == {"configurable": {"thread_id": "1001"}}
    assert invocation["context"].model is model
    assert invocation["version"] == "v2"
    assistant = session.added[0]
    assert assistant.id == 3001
    assert assistant.conversation_id == 1001
    assert assistant.parent_message_id == 2001
    assert assistant.role == "ASSISTANT"
    assert assistant.content == "你好"
    completed = publisher.events[-1][1]
    assert completed.model_dump(mode="json") == {
        "assistant_message_id": "3001",
        "finish_reason": "stop",
    }
    assert all(event != "error" for event, _ in publisher.events)
