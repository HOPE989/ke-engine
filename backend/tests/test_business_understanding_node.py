import importlib
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from app.domains.chat.graph.business_understanding import BusinessUnderstandingResult
from app.domains.chat.graph.context import ChatRuntimeContext
from app.domains.chat.graph.nodes.business_understanding import business_understanding_node


class FakeStructuredRunnable:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return self.result


class FakeStructuredModel:
    def __init__(self, runnable):
        self.runnable = runnable
        self.schemas = []

    def with_structured_output(self, schema):
        self.schemas.append(schema)
        return self.runnable


class FailingStructuredRunnable:
    def __init__(self, error):
        self.error = error
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        raise self.error


@pytest.mark.asyncio
async def test_business_understanding_node_uses_injected_structured_model_and_full_history():
    result = BusinessUnderstandingResult.model_validate(
        {
            "reasoning": "提供了具体运单号",
            "route": "BUSINESS",
            "intent": "BUSINESS_DATA_QUERY",
            "entities": {"document_type": "运单", "document_no": "YD2026001"},
            "clarification_question": None,
        }
    )
    runnable = FakeStructuredRunnable(result)
    model = FakeStructuredModel(runnable)
    history = [
        HumanMessage(content="查运单YD2026001"),
        AIMessage(content="请说明具体需求"),
        HumanMessage(content="查询当前状态"),
    ]

    update = await business_understanding_node(
        {"messages": history}, Runtime(context=ChatRuntimeContext(model=model))
    )

    assert model.schemas == [BusinessUnderstandingResult]
    assert runnable.calls[0][1:] == history
    assert update == {"business_understanding": result}


@pytest.mark.asyncio
async def test_business_understanding_node_propagates_model_failure_without_retry_or_state_update():
    error = RuntimeError("structured output unavailable")
    runnable = FailingStructuredRunnable(error)
    model = FakeStructuredModel(runnable)
    history = [HumanMessage(content="查询运单状态")]
    state = {"messages": history}

    with pytest.raises(RuntimeError) as raised:
        await business_understanding_node(
            state, Runtime(context=ChatRuntimeContext(model=model))
        )

    assert raised.value is error
    assert model.schemas == [BusinessUnderstandingResult]
    assert len(runnable.calls) == 1
    assert state == {"messages": history}


def test_business_understanding_state_only_declares_checkpointable_result():
    from app.domains.chat.graph.state import ChatState

    assert ChatState.__annotations__["business_understanding"] is BusinessUnderstandingResult


def test_business_understanding_node_is_exported_by_graph_packages():
    from app.domains.chat.graph import business_understanding_node as graph_node
    from app.domains.chat.graph.nodes import business_understanding_node as nodes_node

    assert graph_node is business_understanding_node
    assert nodes_node is business_understanding_node


def test_importing_business_understanding_node_does_not_initialize_runtime_resources(monkeypatch):
    from app.core import config
    from app.infrastructure import llm
    from app.infrastructure.db import session

    def explode(*args, **kwargs):
        raise AssertionError("node import must not initialize runtime resources")

    monkeypatch.setattr(config, "get_settings", explode)
    monkeypatch.setattr(llm, "create_chat_model", explode)
    monkeypatch.setattr(session, "get_session_factory", explode)
    sys.modules.pop("app.domains.chat.graph.nodes.business_understanding", None)

    imported = importlib.import_module(
        "app.domains.chat.graph.nodes.business_understanding"
    )

    assert callable(imported.business_understanding_node)
