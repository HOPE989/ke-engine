import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.domains.chat.graph.query_contextualization import QueryContextInput
from app.domains.chat.graph.query_contextualization.prompt import (
    QUERY_CONTEXTUALIZATION_PROMPT_VERSION,
    QUERY_CONTEXTUALIZATION_SYSTEM_PROMPT,
    build_query_contextualization_messages,
)


def test_query_context_prompt_is_chat_owned_and_forbids_source_routing():
    assert QUERY_CONTEXTUALIZATION_PROMPT_VERSION == "v3"
    for token in [
        "Chat 服务",
        "当前问题",
        "只生成一条",
        "不得回答",
        "不得选择 Retriever",
        "不得生成 SQL",
        "不得生成 Cypher",
        "实体",
        "时间",
        "数字",
        "否定",
        "不得臆造",
    ]:
        assert token in QUERY_CONTEXTUALIZATION_SYSTEM_PROMPT


def test_query_context_prompt_serializes_input_as_user_json_data():
    request = QueryContextInput.model_validate(
        {
            "original_query": "按实际版呢",
            "conversation_context": [
                {"role": "user", "content": "查询神木站本月模拟版装车计划"}
            ],
            "business_context": {
                "intent": "BUSINESS_DATA_QUERY",
                "entities": {"departure_station": "神木站"},
            },
        }
    )

    messages = build_query_contextualization_messages(request)

    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    marker, raw_json = str(messages[1].content).split("\n", maxsplit=1)
    assert marker == "INPUT_JSON"
    assert json.loads(raw_json) == request.model_dump(mode="json")
