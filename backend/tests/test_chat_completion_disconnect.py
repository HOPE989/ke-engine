import asyncio

from langchain_core.messages import AIMessageChunk
from langgraph.types import Interrupt, StateSnapshot
import pytest

from app.domains.chat.graph.routing import CLARIFY_NODE, LLM_NODE
from app.domains.chat.services.conversation import AcceptedUserTurn


class NoPendingStateGraph:
    async def aget_state(self, config):
        return StateSnapshot(
            values={},
            next=(),
            config=config,
            metadata=None,
            created_at=None,
            parent_config=None,
            tasks=(),
            interrupts=(),
        )


class GatedGraph(NoPendingStateGraph):
    def __init__(self, first_delta_sent, continue_running, calls):
        self.first_delta_sent = first_delta_sent
        self.continue_running = continue_running
        self.calls = calls
        self.cancelled = False

    async def astream_events(self, *args, **kwargs):
        try:
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": AIMessageChunk(content="first")},
                "metadata": {"langgraph_node": LLM_NODE},
            }
            self.first_delta_sent.set()
            await self.continue_running.wait()
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": AIMessageChunk(content="second")},
                "metadata": {"langgraph_node": LLM_NODE},
            }
            self.calls.append("graph_complete")
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class GatedClarificationGraph(NoPendingStateGraph):
    def __init__(self, interrupt_ready, release_interrupt, calls):
        self.interrupt_ready = interrupt_ready
        self.release_interrupt = release_interrupt
        self.calls = calls
        self.cancelled = False

    async def astream_events(self, *args, **kwargs):
        try:
            self.interrupt_ready.set()
            await self.release_interrupt.wait()
            self.calls.append("graph_released")
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
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class FullQueueThenClarificationGraph(NoPendingStateGraph):
    def __init__(
        self,
        blocked_publish_started,
        publish_resumed,
        release_interrupt,
        calls,
    ):
        self.blocked_publish_started = blocked_publish_started
        self.publish_resumed = publish_resumed
        self.release_interrupt = release_interrupt
        self.calls = calls
        self.cancelled = False

    async def astream_events(self, *args, **kwargs):
        try:
            for index in range(17):
                if index == 16:
                    self.blocked_publish_started.set()
                yield {
                    "event": "on_chat_model_stream",
                    "data": {"chunk": AIMessageChunk(content=str(index))},
                    "metadata": {"langgraph_node": LLM_NODE},
                }

            self.publish_resumed.set()
            await self.release_interrupt.wait()
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
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class FakeTransaction:
    def __init__(self, calls):
        self.calls = calls

    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.calls.append("assistant_commit")


class FakeSession:
    def __init__(self, calls):
        self.calls = calls
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def begin(self):
        return FakeTransaction(self.calls)

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
async def test_subscriber_disconnect_does_not_cancel_producer_or_queue_later_tokens():
    from app.domains.chat.services.runtime import CompletionProducer, CompletionProducerRegistry

    calls = []
    first_delta_sent = asyncio.Event()
    continue_running = asyncio.Event()
    graph = GatedGraph(first_delta_sent, continue_running, calls)
    session = FakeSession(calls)
    registry = CompletionProducerRegistry(shutdown_timeout=1)

    def producer_factory(publisher):
        return CompletionProducer(
            graph=graph,
            model=object(),
            session_factory=FakeSessionFactory(session),
            id_generator=FakeIdGenerator(),
            publisher=publisher,
        )

    subscriber = registry.start(
        producer_factory=producer_factory,
        turn=AcceptedUserTurn(1001, 2001, "hello"),
        user_id="alice",
    )
    assert (await subscriber.receive())[0] == "metadata"
    assert (await subscriber.receive())[0] == "content_delta"
    await first_delta_sent.wait()

    subscriber.detach()
    pending_at_detach = subscriber.pending_count
    continue_running.set()
    await registry.shutdown()

    assert graph.cancelled is False
    assert calls == ["graph_complete", "assistant_commit"]
    assert session.added[0].content == "firstsecond"
    assert subscriber.pending_count == pending_at_detach == 0
    assert registry.active_count == 0


@pytest.mark.asyncio
async def test_disconnect_after_metadata_still_persists_clarification_interrupt():
    from app.domains.chat.services.runtime import (
        CompletionProducer,
        CompletionProducerRegistry,
    )

    calls = []
    interrupt_ready = asyncio.Event()
    release_interrupt = asyncio.Event()
    graph = GatedClarificationGraph(interrupt_ready, release_interrupt, calls)
    session = FakeSession(calls)
    registry = CompletionProducerRegistry(shutdown_timeout=1)

    def producer_factory(publisher):
        return CompletionProducer(
            graph=graph,
            model=object(),
            session_factory=FakeSessionFactory(session),
            id_generator=FakeIdGenerator(),
            publisher=publisher,
        )

    subscriber = registry.start(
        producer_factory=producer_factory,
        turn=AcceptedUserTurn(1001, 2001, "查一下我的运单"),
        user_id="alice",
    )
    assert (await subscriber.receive())[0] == "metadata"

    subscriber.detach()
    await interrupt_ready.wait()
    pending_at_detach = subscriber.pending_count
    release_interrupt.set()
    await registry.shutdown()

    assert graph.cancelled is False
    assert calls == ["graph_released", "assistant_commit"]
    assert session.added[0].content == "请提供运单号"
    assert subscriber.pending_count == pending_at_detach == 0
    assert registry.active_count == 0


@pytest.mark.asyncio
async def test_detach_unblocks_publish_when_channel_queue_is_full():
    from app.domains.chat.services.runtime import (
        CompletionProducer,
        CompletionProducerRegistry,
    )

    calls = []
    blocked_publish_started = asyncio.Event()
    publish_resumed = asyncio.Event()
    release_interrupt = asyncio.Event()
    graph = FullQueueThenClarificationGraph(
        blocked_publish_started,
        publish_resumed,
        release_interrupt,
        calls,
    )
    session = FakeSession(calls)
    registry = CompletionProducerRegistry(shutdown_timeout=1)

    def producer_factory(publisher):
        return CompletionProducer(
            graph=graph,
            model=object(),
            session_factory=FakeSessionFactory(session),
            id_generator=FakeIdGenerator(),
            publisher=publisher,
        )

    subscriber = registry.start(
        producer_factory=producer_factory,
        turn=AcceptedUserTurn(1001, 2001, "查一下我的运单"),
        user_id="alice",
    )
    assert (await subscriber.receive())[0] == "metadata"
    await blocked_publish_started.wait()
    assert subscriber.pending_count == 16
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(publish_resumed.wait(), timeout=0.05)

    subscriber.detach()
    try:
        await asyncio.wait_for(publish_resumed.wait(), timeout=0.1)
        detach_unblocked_publish = True
    except TimeoutError:
        detach_unblocked_publish = False
        await subscriber.receive()
        await asyncio.wait_for(publish_resumed.wait(), timeout=0.1)

    release_interrupt.set()
    await registry.shutdown()

    assert detach_unblocked_publish is True
    assert graph.cancelled is False
    assert session.added[0].content == "请提供运单号"
    assert subscriber.pending_count == 0
    assert registry.active_count == 0


@pytest.mark.asyncio
async def test_registry_shutdown_rejects_new_producers():
    from app.domains.chat.services.runtime import CompletionProducerRegistry

    registry = CompletionProducerRegistry(shutdown_timeout=1)
    await registry.shutdown()

    with pytest.raises(RuntimeError, match="shutting down"):
        registry.start(
            producer_factory=lambda publisher: object(),
            turn=AcceptedUserTurn(1001, 2001, "hello"),
            user_id="alice",
        )
