import asyncio

from langchain_core.messages import AIMessage
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domains.chat.graph import build_chat_graph
from app.domains.chat.services.conversation import AcceptedUserTurn
from app.domains.chat.services.runtime import CompletionProducer
from app.domains.chat.shared.models import Conversation, Message
from app.infrastructure.db.base import Base
from app.infrastructure.langgraph import postgres_checkpointer
from tests.chat_postgres_support import (
    BlockingPartialModel,
    create_business_engine,
    isolated_schema,
)


class RecordingPublisher:
    def __init__(self):
        self.events = []

    async def publish(self, event, payload):
        self.events.append((event, payload))


class FixedIdGenerator:
    def next_id(self):
        return 3001


@pytest.mark.integration
@pytest.mark.asyncio
async def test_aborted_run_does_not_checkpoint_partial_ai_message_or_retry_model():
    async with isolated_schema() as (schema, saver_url):
        engine = create_business_engine(schema)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory.begin() as session:
                session.add(
                    Conversation(
                        id=1001,
                        user_id="alice",
                        title="durable user input",
                        status="ACTIVE",
                    )
                )
                session.add(
                    Message(
                        id=2001,
                        conversation_id=1001,
                        role="USER",
                        content="durable user input",
                    )
                )

            async with postgres_checkpointer(saver_url) as saver:
                graph = build_chat_graph().compile(checkpointer=saver)
                model = BlockingPartialModel()
                publisher = RecordingPublisher()
                producer = CompletionProducer(
                    graph=graph,
                    model=model,
                    session_factory=session_factory,
                    id_generator=FixedIdGenerator(),
                    publisher=publisher,
                )
                run = asyncio.create_task(
                    producer.run(
                        turn=AcceptedUserTurn(1001, 2001, "durable user input"),
                        user_id="alice",
                    )
                )
                await asyncio.wait_for(model.started.wait(), timeout=2)
                assert [chunk.content for chunk in model.partial_chunks] == ["not-durable"]
                run.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await run

                config = {"configurable": {"thread_id": "1001"}}
                state = await graph.aget_state(config)
                contents = [message.content for message in state.values["messages"]]
                assert "not-durable" not in contents
                assert not any(isinstance(message, AIMessage) for message in state.values["messages"])

            async with session_factory() as session:
                messages = list(
                    (
                        await session.execute(
                            select(Message).order_by(Message.created_at, Message.id)
                        )
                    )
                    .scalars()
                    .all()
                )
            assert [(message.role, message.content) for message in messages] == [
                ("USER", "durable user input")
            ]
            await asyncio.sleep(0)
            assert model.calls == 1
            assert [event for event, _ in publisher.events] == ["metadata"]
        finally:
            await engine.dispose()
