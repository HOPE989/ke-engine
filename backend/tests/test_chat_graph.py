import importlib
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START
from langgraph.runtime import Runtime


class FakeChatModel:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return self.response


def test_chat_graph_exposes_stable_public_imports_and_node_name():
    from app.domains.chat.graph import (
        ChatRuntimeContext,
        ChatState,
        LLM_NODE,
        build_chat_graph,
        llm_node,
    )

    assert ChatRuntimeContext
    assert ChatState
    assert LLM_NODE == "llm"
    assert callable(build_chat_graph)
    assert callable(llm_node)


def test_importing_chat_graph_does_not_initialize_runtime_resources(monkeypatch):
    from app.core import config
    from app.infrastructure import llm
    from app.infrastructure.db import session

    def explode(*args, **kwargs):
        raise AssertionError("graph import must not initialize runtime resources")

    monkeypatch.setattr(config, "get_settings", explode)
    monkeypatch.setattr(llm, "create_chat_model", explode)
    monkeypatch.setattr(session, "get_session_factory", explode)
    for name in list(sys.modules):
        if name.startswith("app.domains.chat.graph"):
            sys.modules.pop(name)

    imported = importlib.import_module("app.domains.chat.graph.builder")

    assert callable(imported.build_chat_graph)


def test_chat_graph_has_only_start_llm_end_and_no_retry_policy():
    from app.domains.chat.graph.builder import build_chat_graph

    builder = build_chat_graph()
    compiled = builder.compile()

    assert {(edge.source, edge.target) for edge in compiled.get_graph().edges} == {
        (START, "llm"),
        ("llm", END),
    }
    assert set(builder.nodes) == {"llm"}
    assert builder.nodes["llm"].retry_policy is None


@pytest.mark.asyncio
async def test_llm_node_uses_injected_model_and_returns_ai_message_update():
    from app.domains.chat.graph.context import ChatRuntimeContext
    from app.domains.chat.graph.nodes.llm import llm_node

    user_message = HumanMessage(content="hello")
    ai_message = AIMessage(content="world")
    model = FakeChatModel(ai_message)

    update = await llm_node(
        {"messages": [user_message]},
        Runtime(context=ChatRuntimeContext(model=model)),
    )

    assert model.calls == [[user_message]]
    assert update == {"messages": [ai_message]}


@pytest.mark.asyncio
async def test_chat_graph_merges_llm_update_with_messages_state_semantics():
    from app.domains.chat.graph.builder import build_chat_graph
    from app.domains.chat.graph.context import ChatRuntimeContext

    user_message = HumanMessage(content="hello")
    ai_message = AIMessage(content="world")
    model = FakeChatModel(ai_message)
    graph = build_chat_graph().compile()

    result = await graph.ainvoke(
        {"messages": [user_message]},
        context=ChatRuntimeContext(model=model),
    )

    assert result["messages"] == [user_message, ai_message]
