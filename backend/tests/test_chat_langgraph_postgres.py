from langchain_core.messages import HumanMessage
import pytest

from app.domains.chat.graph import ChatRuntimeContext, build_chat_graph
from app.infrastructure.langgraph import postgres_checkpointer
from tests.chat_postgres_support import (
    FailingModel,
    RecordingModel,
    isolated_schema,
    unique_thread_id,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_checkpoint_resumes_same_thread_isolates_others_and_keeps_last_success():
    async with isolated_schema() as (_, saver_url):
        async with postgres_checkpointer(saver_url) as saver:
            graph = build_chat_graph().compile(checkpointer=saver)
            model = RecordingModel()
            thread_id = unique_thread_id()
            config = {"configurable": {"thread_id": thread_id}}
            await graph.ainvoke(
                {"messages": [HumanMessage(content="first")]},
                config,
                context=ChatRuntimeContext(model=model),
            )
            await graph.ainvoke(
                {"messages": [HumanMessage(content="second")]},
                config,
                context=ChatRuntimeContext(model=model),
            )
            assert [message.content for message in model.calls[1]] == [
                "first",
                "answer-1",
                "second",
            ]

            other = await graph.aget_state(
                {"configurable": {"thread_id": unique_thread_id()}}
            )
            assert other.values == {}

            failing = FailingModel()
            with pytest.raises(RuntimeError, match="controlled failure"):
                await graph.ainvoke(
                    {"messages": [HumanMessage(content="failed-turn")]},
                    config,
                    context=ChatRuntimeContext(model=failing),
                )
            state = await graph.aget_state(config)
            contents = [message.content for message in state.values["messages"]]
            assert "partial" not in contents
            assert contents[-1] == "failed-turn"
            assert failing.calls == 1
