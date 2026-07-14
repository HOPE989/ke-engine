"""Chat completion Graph producer。"""

from typing import Any

from langchain_core.messages import HumanMessage

from app.contracts.chat.stream import CompletedPayload, MetadataPayload
from app.domains.chat.graph import ChatRuntimeContext
from app.domains.chat.repositories import MessageRepository
from app.domains.chat.services.conversation import AcceptedUserTurn
from app.services.chat_api.streaming import project_graph_event


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

        answer = await self._accumulate_answer(turn)
        assistant_message_id = await self._commit_assistant(turn, answer)
        await self._publisher.publish(
            "completed",
            CompletedPayload(assistant_message_id=assistant_message_id),
        )

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
