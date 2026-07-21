import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.domains.chat.graph.business_understanding import BusinessUnderstandingResult
from chat_graph_test_support import FakeSequentialChatModel


def make_clarify_result() -> BusinessUnderstandingResult:
    return BusinessUnderstandingResult.model_validate(
        {
            "reasoning": "缺少执行查询所需的运单号",
            "route": "CLARIFY",
            "intent": "BUSINESS_DATA_QUERY",
            "entities": {"document_type": "运单"},
            "clarification_question": "请提供运单号",
        }
    )


def make_business_result() -> BusinessUnderstandingResult:
    return BusinessUnderstandingResult.model_validate(
        {
            "reasoning": "已取得具体运单号",
            "route": "BUSINESS",
            "intent": "BUSINESS_DATA_QUERY",
            "entities": {"document_type": "运单", "document_no": "YD2026001"},
            "clarification_question": None,
        }
    )


def test_clarify_resume_returns_command_to_business_understanding(monkeypatch):
    from app.domains.chat.graph.nodes import clarify as clarify_module

    monkeypatch.setattr(clarify_module, "interrupt", lambda payload: " YD2026001 ")

    command = clarify_module.clarify_node(
        {"messages": [], "business_understanding": make_clarify_result()}
    )

    assert isinstance(command, Command)
    assert command.goto == "business_understanding"
    assert [message.content for message in command.update["messages"]] == [
        "请提供运单号",
        "YD2026001",
    ]


@pytest.mark.asyncio
async def test_clarify_route_suspends_with_typed_payload():
    from app.domains.chat.graph.builder import build_chat_graph
    from app.domains.chat.graph.context import ChatRuntimeContext

    model = FakeSequentialChatModel([make_clarify_result()])
    graph = build_chat_graph().compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "clarify-suspend-thread"}}

    await graph.ainvoke(
        {"messages": [HumanMessage(content="查一下我的运单")]},
        config,
        context=ChatRuntimeContext(model=model),
    )
    snapshot = await graph.aget_state(config)

    assert snapshot.next == ("clarify",)
    assert [message.content for message in snapshot.values["messages"]] == [
        "查一下我的运单"
    ]
    assert len(snapshot.tasks) == 1
    assert snapshot.tasks[0].name == "clarify"
    assert snapshot.tasks[0].interrupts[0].value == {
        "kind": "business_clarification",
        "question": "请提供运单号",
    }


@pytest.mark.asyncio
async def test_clarify_resume_adds_question_and_answer_before_reclassification():
    from app.domains.chat.graph.builder import build_chat_graph
    from app.domains.chat.graph.context import ChatRuntimeContext
    from app.domains.chat.graph.nodes.business_boundary import BUSINESS_BOUNDARY_MESSAGE

    model = FakeSequentialChatModel([make_clarify_result(), make_business_result()])
    graph = build_chat_graph().compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "clarify-resume-thread"}}
    context = ChatRuntimeContext(model=model)

    await graph.ainvoke(
        {"messages": [HumanMessage(content="查一下我的运单")]},
        config,
        context=context,
    )
    result = await graph.ainvoke(
        Command(resume="YD2026001"),
        config,
        context=context,
    )

    second_history = model.structured_runnable.calls[1]
    assert isinstance(second_history[-2], AIMessage)
    assert second_history[-2].content == "请提供运单号"
    assert isinstance(second_history[-1], HumanMessage)
    assert second_history[-1].content == "YD2026001"
    assert result["messages"][-1].content == BUSINESS_BOUNDARY_MESSAGE
    assert model.ordinary_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("resume_value", ["   ", 42])
async def test_clarify_resume_rejects_non_text_or_blank_content(resume_value):
    from app.domains.chat.graph.builder import build_chat_graph
    from app.domains.chat.graph.context import ChatRuntimeContext

    model = FakeSequentialChatModel([make_clarify_result()])
    graph = build_chat_graph().compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": f"invalid-resume-{resume_value!r}"}}
    context = ChatRuntimeContext(model=model)

    await graph.ainvoke(
        {"messages": [HumanMessage(content="查一下我的运单")]},
        config,
        context=context,
    )

    with pytest.raises(
        ValueError,
        match="clarification resume content must be non-blank text",
    ):
        await graph.ainvoke(Command(resume=resume_value), config, context=context)
