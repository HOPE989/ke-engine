import asyncio

from langchain_core.messages import AIMessageChunk
import pytest

from app.domains.chat.services.conversation import AcceptedUserTurn


class GatedGraph:
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
            }
            self.first_delta_sent.set()
            await self.continue_running.wait()
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": AIMessageChunk(content="second")},
            }
            self.calls.append("graph_complete")
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
