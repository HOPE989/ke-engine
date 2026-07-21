from collections.abc import AsyncIterator
import logging

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domains.chat.graph import build_chat_graph
from app.domains.chat.graph.business_understanding import BusinessUnderstandingResult
from app.domains.chat.graph.nodes.business_boundary import BUSINESS_BOUNDARY_MESSAGE
from app.domains.chat.services.conversation import AcceptedUserTurn
from app.domains.chat.services.runtime import CompletionProducer
from app.domains.chat.shared.models import Conversation, Message
from app.infrastructure.db.base import Base
from app.infrastructure.langgraph import postgres_checkpointer
from tests.chat_postgres_support import (
    ScriptedChatModel,
    create_business_engine,
    isolated_schema,
)


def clarify_result() -> BusinessUnderstandingResult:
    return BusinessUnderstandingResult.model_validate(
        {
            "reasoning": "缺少执行查询所需的运单号",
            "route": "CLARIFY",
            "intent": "BUSINESS_DATA_QUERY",
            "entities": {"document_type": "运单"},
            "clarification_question": "请提供运单号",
        }
    )


def business_result() -> BusinessUnderstandingResult:
    return BusinessUnderstandingResult.model_validate(
        {
            "reasoning": "澄清回答提供了具体运单号",
            "route": "BUSINESS",
            "intent": "BUSINESS_DATA_QUERY",
            "entities": {
                "document_type": "运单",
                "document_no": "YD2026001",
            },
            "clarification_question": None,
        }
    )


def non_business_result() -> BusinessUnderstandingResult:
    return BusinessUnderstandingResult.model_validate(
        {
            "reasoning": "这是普通寒暄，不属于企业铁路或煤炭业务",
            "route": "NON_BUSINESS",
            "intent": None,
            "entities": {},
            "clarification_question": None,
        }
    )


class SequenceIdGenerator:
    def __init__(self, values: list[int]) -> None:
        self.values = iter(values)

    def next_id(self) -> int:
        return next(self.values)


class RecordingCompiledGraph:
    def __init__(self, graph) -> None:
        self.graph = graph
        self.stream_inputs = []
        self.stream_events = []

    async def aget_state(self, config):
        return await self.graph.aget_state(config)

    async def astream_events(
        self, graph_input, config, *, context, version
    ) -> AsyncIterator[dict[str, object]]:
        self.stream_inputs.append(graph_input)
        async for event in self.graph.astream_events(
            graph_input,
            config,
            context=context,
            version=version,
        ):
            self.stream_events.append(event)
            yield event


class PersistenceObservingPublisher:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory
        self.events = []
        self.persisted_at_completed: list[tuple[str, str]] = []

    async def publish(self, event, payload) -> None:
        if event == "completed":
            async with self.session_factory() as session:
                message = await session.get(Message, int(payload.assistant_message_id))
            assert message is not None
            self.persisted_at_completed.append((message.role, message.content))
        self.events.append((event, payload))


async def persisted_messages(session_factory) -> list[Message]:
    async with session_factory() as session:
        return list(
            (
                await session.execute(
                    select(Message).order_by(Message.id)
                )
            )
            .scalars()
            .all()
        )


async def seed_conversation(
    session_factory,
    *,
    content: str,
    conversation_id: int = 1001,
    user_message_id: int = 2001,
) -> None:
    async with session_factory.begin() as session:
        session.add(
            Conversation(
                id=conversation_id,
                user_id="alice",
                title=content,
                status="ACTIVE",
            )
        )
        session.add(
            Message(
                id=user_message_id,
                conversation_id=conversation_id,
                role="USER",
                content=content,
            )
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_non_business_streams_general_answer_and_persists_before_completed():
    answer = "你好，我可以帮你处理普通问答。"
    async with isolated_schema() as (schema, saver_url):
        engine = create_business_engine(schema)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await seed_conversation(session_factory, content="你好")
            async with postgres_checkpointer(saver_url) as saver:
                compiled = build_chat_graph().compile(checkpointer=saver)
                graph = RecordingCompiledGraph(compiled)
                model = ScriptedChatModel(
                    structured_outputs=[non_business_result()],
                    ordinary_outputs=[AIMessage(content=answer)],
                )
                publisher = PersistenceObservingPublisher(session_factory)
                producer = CompletionProducer(
                    graph=graph,
                    model=model,
                    session_factory=session_factory,
                    id_generator=SequenceIdGenerator([3001]),
                    publisher=publisher,
                )

                await producer.run(
                    turn=AcceptedUserTurn(1001, 2001, "你好"),
                    user_id="alice",
                )

                deltas = [
                    payload.content
                    for event, payload in publisher.events
                    if event == "content_delta"
                ]
                assert "".join(deltas) == answer
                assert publisher.events[0][0] == "metadata"
                assert publisher.events[-1][0] == "completed"
                assert publisher.events[-1][1].finish_reason == "stop"
                assert publisher.persisted_at_completed == [("ASSISTANT", answer)]
                assert len(model.ordinary_calls) == 1
                assert model.ordinary_calls[0][-1].content == "你好"
                assert any(
                    event.get("event") == "on_chat_model_stream"
                    and event.get("metadata", {}).get("langgraph_node") == "llm"
                    for event in graph.stream_events
                )

            messages = await persisted_messages(session_factory)
            assert [(message.role, message.content) for message in messages] == [
                ("USER", "你好"),
                ("ASSISTANT", answer),
            ]
            assert messages[-1].parent_message_id == 2001
            public_payloads = " ".join(
                payload.model_dump_json() for _, payload in publisher.events
            )
            assert non_business_result().reasoning not in public_payloads
        finally:
            await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_business_persists_only_boundary_message_without_ordinary_model_call():
    content = "查一下运单YD2026001现在到哪了"
    async with isolated_schema() as (schema, saver_url):
        engine = create_business_engine(schema)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await seed_conversation(session_factory, content=content)
            async with postgres_checkpointer(saver_url) as saver:
                compiled = build_chat_graph().compile(checkpointer=saver)
                graph = RecordingCompiledGraph(compiled)
                model = ScriptedChatModel(
                    structured_outputs=[business_result()],
                    ordinary_outputs=[],
                )
                publisher = PersistenceObservingPublisher(session_factory)
                producer = CompletionProducer(
                    graph=graph,
                    model=model,
                    session_factory=session_factory,
                    id_generator=SequenceIdGenerator([3001]),
                    publisher=publisher,
                )

                await producer.run(
                    turn=AcceptedUserTurn(1001, 2001, content),
                    user_id="alice",
                )

                assert [event for event, _ in publisher.events] == [
                    "metadata",
                    "content_delta",
                    "completed",
                ]
                assert publisher.events[1][1].content == BUSINESS_BOUNDARY_MESSAGE
                assert publisher.events[-1][1].finish_reason == "stop"
                assert publisher.persisted_at_completed == [
                    ("ASSISTANT", BUSINESS_BOUNDARY_MESSAGE)
                ]
                assert model.ordinary_calls == []
                assert any(
                    event.get("event") == "on_chain_stream"
                    and event.get("metadata", {}).get("langgraph_node")
                    == "business_boundary"
                    for event in graph.stream_events
                )
                snapshot = await compiled.aget_state(
                    {"configurable": {"thread_id": "1001"}}
                )
                assert snapshot.next == ()
                assert snapshot.tasks == ()

            messages = await persisted_messages(session_factory)
            assert [(message.role, message.content) for message in messages] == [
                ("USER", content),
                ("ASSISTANT", BUSINESS_BOUNDARY_MESSAGE),
            ]
            assert messages[-1].parent_message_id == 2001
            public_payloads = " ".join(
                payload.model_dump_json() for _, payload in publisher.events
            )
            assert business_result().reasoning not in public_payloads
        finally:
            await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_clarification_persists_resumes_and_reclassifies_on_same_thread(caplog):
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
                        title="查一下我的运单",
                        status="ACTIVE",
                    )
                )
                session.add(
                    Message(
                        id=2001,
                        conversation_id=1001,
                        role="USER",
                        content="查一下我的运单",
                    )
                )

            async with postgres_checkpointer(saver_url) as saver:
                compiled = build_chat_graph().compile(checkpointer=saver)
                graph = RecordingCompiledGraph(compiled)
                model = ScriptedChatModel(
                    structured_outputs=[clarify_result(), business_result()],
                    ordinary_outputs=[],
                )
                id_generator = SequenceIdGenerator([3001, 3002])

                first_publisher = PersistenceObservingPublisher(session_factory)
                first_producer = CompletionProducer(
                    graph=graph,
                    model=model,
                    session_factory=session_factory,
                    id_generator=id_generator,
                    publisher=first_publisher,
                )
                await first_producer.run(
                    turn=AcceptedUserTurn(1001, 2001, "查一下我的运单"),
                    user_id="alice",
                )

                assert [event for event, _ in first_publisher.events] == [
                    "metadata",
                    "content_delta",
                    "completed",
                ]
                assert first_publisher.events[1][1].content == "请提供运单号"
                assert first_publisher.events[-1][1].finish_reason == "interrupt"
                assert first_publisher.persisted_at_completed == [
                    ("ASSISTANT", "请提供运单号")
                ]
                config = {"configurable": {"thread_id": "1001"}}
                interrupted = await compiled.aget_state(config)
                assert interrupted.next == ("clarify",)
                assert len(interrupted.tasks) == 1

                async with session_factory.begin() as session:
                    session.add(
                        Message(
                            id=2002,
                            conversation_id=1001,
                            role="USER",
                            content="YD2026001",
                        )
                    )

                second_publisher = PersistenceObservingPublisher(session_factory)
                second_producer = CompletionProducer(
                    graph=graph,
                    model=model,
                    session_factory=session_factory,
                    id_generator=id_generator,
                    publisher=second_publisher,
                )
                await second_producer.run(
                    turn=AcceptedUserTurn(1001, 2002, "YD2026001"),
                    user_id="alice",
                )

                assert isinstance(graph.stream_inputs[1], Command)
                assert graph.stream_inputs[1].resume == "YD2026001"
                second_history = model.structured_calls[1]
                assert isinstance(second_history[-2], AIMessage)
                assert second_history[-2].content == "请提供运单号"
                assert isinstance(second_history[-1], HumanMessage)
                assert second_history[-1].content == "YD2026001"
                assert [event for event, _ in second_publisher.events] == [
                    "metadata",
                    "content_delta",
                    "completed",
                ]
                assert second_publisher.events[1][1].content == BUSINESS_BOUNDARY_MESSAGE
                assert second_publisher.events[-1][1].finish_reason == "stop"
                assert second_publisher.persisted_at_completed == [
                    ("ASSISTANT", BUSINESS_BOUNDARY_MESSAGE)
                ]
                completed = await compiled.aget_state(config)
                assert completed.next == ()
                assert completed.tasks == ()

            messages = await persisted_messages(session_factory)
            assert [(message.role, message.content) for message in messages] == [
                ("USER", "查一下我的运单"),
                ("USER", "YD2026001"),
                ("ASSISTANT", "请提供运单号"),
                ("ASSISTANT", BUSINESS_BOUNDARY_MESSAGE),
            ]
            assert model.ordinary_calls == []
            assert not [
                record
                for record in caplog.records
                if record.name == "langgraph.checkpoint.serde.jsonplus"
                and record.levelno >= logging.WARNING
            ]
        finally:
            await engine.dispose()
