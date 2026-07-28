import inspect

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime
from langgraph.types import Command

from app.domains.chat.graph.business_understanding import (
    BusinessIntent,
    BusinessRoute,
    BusinessUnderstandingResult,
)
from app.domains.chat.graph.context import ChatRuntimeContext
from app.domains.chat.graph.nodes.business_understanding import (
    business_understanding_node,
)
from chat_graph_test_support import FakeSequentialChatModel


def make_result(route: BusinessRoute) -> BusinessUnderstandingResult:
    payload = {
        "reasoning": "classification completed",
        "route": route,
        "intent": None,
        "clarification_question": None,
    }
    if route is BusinessRoute.BUSINESS:
        payload["intent"] = BusinessIntent.POLICY_RULE_QA
    elif route is BusinessRoute.CLARIFY:
        payload["clarification_question"] = "请说明要查询的业务范围。"
    return BusinessUnderstandingResult.model_validate(payload)


@pytest.mark.parametrize(
    ("route", "expected_node"),
    [
        (BusinessRoute.BUSINESS, "contextualize_query"),
        (BusinessRoute.NON_BUSINESS, "llm"),
        (BusinessRoute.CLARIFY, "clarify"),
    ],
)
@pytest.mark.asyncio
async def test_business_understanding_command_maps_each_route_to_one_node(
    route: BusinessRoute, expected_node: str
):
    result = make_result(route)
    model = FakeSequentialChatModel([result], ordinary_response=None)

    command = await business_understanding_node(
        {"messages": [HumanMessage(content="test")]},
        Runtime(context=ChatRuntimeContext(model=model)),
    )

    assert isinstance(command, Command)
    assert command.update == {
        "business_understanding": result,
        "standalone_query": None,
        "evidence_package": None,
        "rag_references": [],
    }
    assert command.goto == expected_node


def test_builder_does_not_install_external_business_decision_edges():
    from app.domains.chat.graph.builder import build_chat_graph

    source = inspect.getsource(build_chat_graph)

    assert "add_conditional_edges" not in source
    assert "add_edge(CLARIFY_NODE, BUSINESS_UNDERSTANDING_NODE)" not in source


@pytest.mark.asyncio
async def test_non_business_graph_calls_structured_and_ordinary_model_once():
    from app.domains.chat.graph.builder import build_chat_graph
    from app.domains.chat.graph.context import ChatRuntimeContext

    classification = make_result(BusinessRoute.NON_BUSINESS)
    answer = AIMessage(content="通用回答")
    model = FakeSequentialChatModel([classification], answer)
    user_message = HumanMessage(content="你好")

    result = await build_chat_graph().compile().ainvoke(
        {"messages": [user_message]},
        context=ChatRuntimeContext(model=model),
    )

    assert len(model.structured_runnable.calls) == 1
    assert len(model.ordinary_calls) == 1
    assert result["messages"] == [user_message, answer]
    assert classification.reasoning not in [
        message.content for message in result["messages"]
    ]
