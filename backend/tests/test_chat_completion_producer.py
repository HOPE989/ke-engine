from langchain_core.messages import AIMessageChunk, HumanMessage
from langgraph.types import Interrupt
import pytest

from app.domains.chat.graph.routing import (
    BUSINESS_UNDERSTANDING_NODE,
    CLARIFY_NODE,
    LLM_NODE,
)
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
                "metadata": {"langgraph_node": LLM_NODE},
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


class FailingGraph(FakeGraph):
    async def astream_events(self, graph_input, config, *, context, version):
        self.invocations.append({"input": graph_input, "config": config})
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": AIMessageChunk(content="partial")},
            "metadata": {"langgraph_node": LLM_NODE},
        }
        raise RuntimeError(
            "postgresql://user:password@db/app api_key=[TEST_SECRET] traceback"
        )


class FailingCommitTransaction(FakeTransaction):
    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            raise RuntimeError("postgresql://user:password@db/app commit failed")


class FailingCommitSession(FakeSession):
    def begin(self):
        return FailingCommitTransaction(self)


class ClarificationInterruptGraph(FakeGraph):
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
        yield {
            "event": "on_chain_stream",
            "data": {
                "chunk": {
                    "__interrupt__": (
                        Interrupt(
                            value={
                                "kind": "business_clarification",
                                "question": "请提供运单号",
                            },
                            id="internal-interrupt-id",
                        ),
                    )
                }
            },
            "metadata": {"langgraph_node": CLARIFY_NODE},
        }


class ClassifierThenClarificationGraph(ClarificationInterruptGraph):
    async def astream_events(self, graph_input, config, *, context, version):
        yield {
            "event": "on_chat_model_stream",
            "data": {
                "chunk": AIMessageChunk(
                    content='{"reasoning":"CLASSIFIER_REASONING_MUST_NOT_LEAK"}'
                )
            },
            "metadata": {"langgraph_node": BUSINESS_UNDERSTANDING_NODE},
        }
        async for event in super().astream_events(
            graph_input,
            config,
            context=context,
            version=version,
        ):
            yield event
        self.calls.append("consumed_after_interrupt")
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": AIMessageChunk(content="trailing-answer")},
            "metadata": {"langgraph_node": LLM_NODE},
        }


class UnsupportedInterruptGraph(FakeGraph):
    def __init__(self, calls, publisher, interrupt_value):
        super().__init__(calls, publisher)
        self.interrupt_value = interrupt_value

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
        yield {
            "event": "on_chain_stream",
            "data": {
                "chunk": {
                    "__interrupt__": (
                        Interrupt(
                            value=self.interrupt_value,
                            id="raw-internal-interrupt-id",
                        ),
                    )
                }
            },
        }


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


@pytest.mark.asyncio
async def test_clarification_interrupt_persists_before_interrupted_completion():
    from app.domains.chat.services.runtime import CompletionProducer

    calls = []
    publisher = FakePublisher(calls)
    graph = ClarificationInterruptGraph(calls, publisher)
    session = FakeSession(calls)
    producer = CompletionProducer(
        graph=graph,
        model=object(),
        session_factory=FakeSessionFactory(session),
        id_generator=FakeIdGenerator(),
        publisher=publisher,
    )

    await producer.run(
        turn=AcceptedUserTurn(
            conversation_id=1001,
            user_message_id=2001,
            content="查一下我的运单",
        ),
        user_id="alice",
    )

    assert [event for event, _ in publisher.events] == [
        "metadata",
        "content_delta",
        "completed",
    ]
    assert publisher.events[1][1].content == "请提供运单号"
    assert session.added[0].content == "请提供运单号"
    assert calls.index("publish_content_delta") < calls.index("assistant_commit")
    assert calls.index("assistant_commit") < calls.index("publish_completed")
    assert publisher.events[-1][1].finish_reason == "interrupt"


@pytest.mark.asyncio
async def test_clarification_interrupt_never_streams_classifier_output():
    from app.domains.chat.services.runtime import CompletionProducer

    calls = []
    publisher = FakePublisher(calls)
    graph = ClassifierThenClarificationGraph(calls, publisher)
    session = FakeSession(calls)
    producer = CompletionProducer(
        graph=graph,
        model=object(),
        session_factory=FakeSessionFactory(session),
        id_generator=FakeIdGenerator(),
        publisher=publisher,
    )

    await producer.run(
        turn=AcceptedUserTurn(1001, 2001, "查一下我的运单"),
        user_id="alice",
    )

    assert [event for event, _ in publisher.events] == [
        "metadata",
        "content_delta",
        "completed",
    ]
    deltas = [
        payload.content
        for event, payload in publisher.events
        if event == "content_delta"
    ]
    assert deltas == ["请提供运单号"]
    public_payloads = " ".join(
        payload.model_dump_json() for _, payload in publisher.events
    )
    assert "CLASSIFIER_REASONING_MUST_NOT_LEAK" not in public_payloads
    assert session.added[0].content == "请提供运单号"
    assert publisher.events[-1][1].finish_reason == "interrupt"
    assert "consumed_after_interrupt" not in calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "interrupt_value",
    [
        {"kind": "unknown", "question": "raw-question-must-not-leak"},
        {"kind": "business_clarification", "question": ""},
    ],
    ids=["unknown-kind", "empty-question"],
)
async def test_unsupported_interrupt_emits_only_safe_error_without_assistant(
    interrupt_value,
):
    from app.domains.chat.services.runtime import CompletionProducer

    calls = []
    publisher = FakePublisher(calls)
    graph = UnsupportedInterruptGraph(calls, publisher, interrupt_value)
    session = FakeSession(calls)
    producer = CompletionProducer(
        graph=graph,
        model=object(),
        session_factory=FakeSessionFactory(session),
        id_generator=FakeIdGenerator(),
        publisher=publisher,
    )

    await producer.run(
        turn=AcceptedUserTurn(1001, 2001, "查一下我的运单"),
        user_id="alice",
    )

    assert [event for event, _ in publisher.events] == ["metadata", "error"]
    assert session.added == []
    assert all(event != "completed" for event, _ in publisher.events)
    error_json = publisher.events[-1][1].model_dump_json()
    assert "raw-internal-interrupt-id" not in error_json
    assert "raw-question-must-not-leak" not in error_json
    assert "Interrupt" not in error_json


@pytest.mark.asyncio
async def test_completion_producer_graph_failure_emits_safe_error_without_retry_or_assistant():
    from app.domains.chat.services.runtime import CompletionProducer

    calls = []
    publisher = FakePublisher(calls)
    graph = FailingGraph(calls, publisher)
    session = FakeSession(calls)
    turn = AcceptedUserTurn(conversation_id=1001, user_message_id=2001, content="hello")
    producer = CompletionProducer(
        graph=graph,
        model=object(),
        session_factory=FakeSessionFactory(session),
        id_generator=FakeIdGenerator(),
        publisher=publisher,
    )

    await producer.run(turn=turn, user_id="alice")

    assert [event for event, _ in publisher.events] == [
        "metadata",
        "content_delta",
        "error",
    ]
    assert len(graph.invocations) == 1
    assert session.added == []
    assert turn.user_message_id == 2001
    error_json = publisher.events[-1][1].model_dump_json()
    assert "postgresql://" not in error_json
    assert "password" not in error_json
    assert "TEST_SECRET" not in error_json
    assert "traceback" not in error_json.lower()


@pytest.mark.asyncio
async def test_completion_producer_commit_error_emits_error_without_completed():
    from app.domains.chat.services.runtime import CompletionProducer

    calls = []
    publisher = FakePublisher(calls)
    graph = FakeGraph(calls, publisher)
    session = FailingCommitSession(calls)
    producer = CompletionProducer(
        graph=graph,
        model=object(),
        session_factory=FakeSessionFactory(session),
        id_generator=FakeIdGenerator(),
        publisher=publisher,
    )

    await producer.run(
        turn=AcceptedUserTurn(
            conversation_id=1001,
            user_message_id=2001,
            content="hello",
        ),
        user_id="alice",
    )

    assert [event for event, _ in publisher.events][-1] == "error"
    assert sum(event == "error" for event, _ in publisher.events) == 1
    assert all(event != "completed" for event, _ in publisher.events)
    assert len(graph.invocations) == 1
