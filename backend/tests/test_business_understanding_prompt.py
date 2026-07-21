from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


def test_business_understanding_prompt_is_versioned_and_contains_all_control_rules():
    from app.domains.chat.graph.business_understanding.prompt import (
        BUSINESS_UNDERSTANDING_PROMPT_VERSION,
        BUSINESS_UNDERSTANDING_SYSTEM_PROMPT,
    )

    assert BUSINESS_UNDERSTANDING_PROMPT_VERSION == "v1"
    for token in [
        "BUSINESS", "NON_BUSINESS", "CLARIFY", "POLICY_RULE_QA",
        "TRANSPORT_OPERATION_QA", "COAL_SALES_QA",
        "PROFESSIONAL_KNOWLEDGE_QA", "BUSINESS_DATA_QUERY", "OTHER_BUSINESS",
        "高铁客票", "运单", "货票", "运行计划", "编组", "实际版", "模拟版",
    ]:
        assert token in BUSINESS_UNDERSTANDING_SYSTEM_PROMPT
    for forbidden in ["related", "BusinessDomain", "confidence"]:
        assert forbidden not in BUSINESS_UNDERSTANDING_SYSTEM_PROMPT


def test_prompt_builder_keeps_checkpoint_history_after_single_system_message():
    from app.domains.chat.graph.business_understanding.prompt import (
        build_business_understanding_messages,
    )

    history = [
        HumanMessage(content="查神木站模拟装车计划"),
        AIMessage(content="开发阶段边界响应"),
        HumanMessage(content="按实际版呢"),
    ]
    built = build_business_understanding_messages(history)

    assert isinstance(built[0], SystemMessage)
    assert built[1:] == history
