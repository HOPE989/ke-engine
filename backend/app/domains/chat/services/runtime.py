"""Chat completion Graph producer。"""

import asyncio
from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage

from app.contracts.chat.stream import CompletedPayload, ErrorPayload, MetadataPayload
from app.domains.chat.graph import ChatRuntimeContext
from app.domains.chat.repositories import MessageRepository
from app.domains.chat.services.conversation import AcceptedUserTurn
from app.services.chat_api.streaming import project_graph_event


class _CompletionChannel:
    def __init__(self, *, maxsize: int) -> None:
        self.queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self.attached = True

    async def publish(self, event: str, payload: Any) -> None:
        if self.attached:
            await self.queue.put((event, payload))


class CompletionSubscriber:
    def __init__(self, channel: _CompletionChannel) -> None:
        self._channel = channel

    async def receive(self) -> tuple[str, Any]:
        return await self._channel.queue.get()

    def detach(self) -> None:
        self._channel.attached = False

    @property
    def pending_count(self) -> int:
        return self._channel.queue.qsize()


class CompletionProducerRegistry:
    def __init__(self, *, shutdown_timeout: float = 30) -> None:
        self._shutdown_timeout = shutdown_timeout
        self._accepting = True
        self._tasks: set[asyncio.Task[None]] = set()

    def start(
        self,
        *,
        producer_factory: Callable[[Any], "CompletionProducer"],
        turn: AcceptedUserTurn,
        user_id: str,
    ) -> CompletionSubscriber:
        if not self._accepting:
            raise RuntimeError("completion registry is shutting down")
        channel = _CompletionChannel(maxsize=16)
        subscriber = CompletionSubscriber(channel)
        producer = producer_factory(channel)
        task = asyncio.create_task(producer.run(turn=turn, user_id=user_id))
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return subscriber

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def shutdown(self) -> None:
        self._accepting = False
        if not self._tasks:
            return
        _, pending = await asyncio.wait(
            tuple(self._tasks),
            timeout=self._shutdown_timeout,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    @property
    def active_count(self) -> int:
        return len(self._tasks)


class CompletionProducer:
    def __init__(
        self,
        *,
        graph: Any,
        model: Any,
        session_factory: Any,
        id_generator: Any,
        publisher: Any,
    ) -> None:
        self._graph = graph
        self._model = model
        self._session_factory = session_factory
        self._id_generator = id_generator
        self._publisher = publisher

    async def run(self, *, turn: AcceptedUserTurn, user_id: str) -> None:
        await self._publisher.publish(
            "metadata",
            MetadataPayload(
                conversation_id=turn.conversation_id,
                user_message_id=turn.user_message_id,
            ),
        )

        try:
            answer = await self._accumulate_answer(turn)
            assistant_message_id = await self._commit_assistant(turn, answer)
        except Exception:
            terminal_event = "error"
            terminal_payload = ErrorPayload(
                code="COMPLETION_FAILED",
                message="Completion failed",
                retryable=False,
            )
        else:
            terminal_event = "completed"
            terminal_payload = CompletedPayload(assistant_message_id=assistant_message_id)
        await self._publisher.publish(terminal_event, terminal_payload)

    async def _consume_graph_events(self, turn: AcceptedUserTurn):
        async for event in self._graph.astream_events(
            {"messages": [HumanMessage(content=turn.content)]},
            {"configurable": {"thread_id": str(turn.conversation_id)}},
            context=ChatRuntimeContext(model=self._model),
            version="v2",
        ):
            delta = project_graph_event(event)
            if delta is not None:
                yield delta

    async def _accumulate_answer(self, turn: AcceptedUserTurn) -> str:
        answer_parts: list[str] = []
        async for delta in self._consume_graph_events(turn):
            answer_parts.append(delta.content)
            await self._publisher.publish("content_delta", delta)
        return "".join(answer_parts)

    async def _commit_assistant(self, turn: AcceptedUserTurn, answer: str) -> int:
        assistant_message_id = self._id_generator.next_id()
        async with self._session_factory() as session:
            async with session.begin():
                MessageRepository(session).add_assistant(
                    message_id=assistant_message_id,
                    conversation_id=turn.conversation_id,
                    parent_message_id=turn.user_message_id,
                    content=answer,
                )
        return assistant_message_id
