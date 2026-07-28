import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.domains.chat.graph.nodes.contextualize_query import (
    invoke_contextualize_query,
)
from app.domains.chat.graph.query_contextualization import QueryContextResult
from rag_query_rewrite_test_support import (
    RecordingStructuredModel,
    RecordingStructuredRunnable,
)


def business_understanding():
    return {
        "reasoning": "业务数据问题",
        "route": "BUSINESS",
        "intent": "BUSINESS_DATA_QUERY",
        "entities": {"departure_station": "神木站"},
    }


@pytest.mark.asyncio
async def test_contextualize_query_uses_history_entities_and_config():
    result = QueryContextResult(
        standalone_query="集团有多少家煤炭生产企业？"
    )
    runnable = RecordingStructuredRunnable([result])
    model = RecordingStructuredModel(runnable)
    config: RunnableConfig = {"metadata": {"request_id": "1"}}

    update = await invoke_contextualize_query(
        {
            "messages": [
                HumanMessage(content="集团煤炭业务情况"),
                AIMessage(content="你想了解哪方面？"),
                HumanMessage(content="有多少家生产企业？"),
            ],
            "business_understanding": business_understanding(),
        },
        model=model,
        config=config,
    )

    assert model.schemas == [QueryContextResult]
    assert runnable.calls[0][1] is config
    assert update == {
        "standalone_query": "集团有多少家煤炭生产企业？"
    }


@pytest.mark.asyncio
async def test_contextualize_query_falls_back_to_complete_current_question():
    runnable = RecordingStructuredRunnable(error=RuntimeError("failed"))
    model = RecordingStructuredModel(runnable)

    update = await invoke_contextualize_query(
        {
            "messages": [HumanMessage(content="集团有多少家煤炭生产企业？")],
            "business_understanding": business_understanding(),
        },
        model=model,
    )

    assert update["standalone_query"] == "集团有多少家煤炭生产企业？"


@pytest.mark.asyncio
async def test_contextualize_query_propagates_cancellation():
    runnable = RecordingStructuredRunnable(error=asyncio.CancelledError())
    model = RecordingStructuredModel(runnable)

    with pytest.raises(asyncio.CancelledError):
        await invoke_contextualize_query(
            {
                "messages": [HumanMessage(content="查询本月运量")],
                "business_understanding": business_understanding(),
            },
            model=model,
        )
