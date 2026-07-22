from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


def test_business_understanding_prompt_is_versioned_and_contains_all_control_rules():
    from app.domains.chat.graph.business_understanding.prompt import (
        BUSINESS_UNDERSTANDING_PROMPT_VERSION,
        BUSINESS_UNDERSTANDING_SYSTEM_PROMPT,
    )

    assert BUSINESS_UNDERSTANDING_PROMPT_VERSION == "v2"
    for token in [
        "BUSINESS", "NON_BUSINESS", "CLARIFY", "POLICY_RULE_QA",
        "TRANSPORT_OPERATION_QA", "COAL_SALES_QA",
        "PROFESSIONAL_KNOWLEDGE_QA", "BUSINESS_DATA_QUERY", "OTHER_BUSINESS",
        "高铁客票", "运单", "货票", "运行计划", "编组", "实际版", "模拟版",
        "# Role", "# Task", "# Route Taxonomy", "# Business Intent Taxonomy",
        "# Disambiguation Guidelines", "# Entity Extraction Rules",
        "# Output JSON Structure", "# Few-Shot Examples",
    ]:
        assert token in BUSINESS_UNDERSTANDING_SYSTEM_PROMPT
    for forbidden in ["related", "BusinessDomain", "confidence"]:
        assert forbidden not in BUSINESS_UNDERSTANDING_SYSTEM_PROMPT


def test_business_understanding_prompt_explicitly_requests_json_output():
    from app.domains.chat.graph.business_understanding.prompt import (
        BUSINESS_UNDERSTANDING_SYSTEM_PROMPT,
    )

    assert "json" in BUSINESS_UNDERSTANDING_SYSTEM_PROMPT.lower()


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


def test_prompt_explicitly_defines_history_inheritance_and_all_route_examples():
    from app.domains.chat.graph.business_understanding.prompt import (
        BUSINESS_UNDERSTANDING_SYSTEM_PROMPT,
    )

    for token in [
        "唯一确定",
        "按实际版呢",
        "继承",
        "不得臆造",
        '"route":"BUSINESS"',
        '"route":"NON_BUSINESS"',
        '"route":"CLARIFY"',
        '"intent":"BUSINESS_DATA_QUERY"',
        '"clarification_question":"请提供运单号"',
    ]:
        assert token in BUSINESS_UNDERSTANDING_SYSTEM_PROMPT


def test_prompt_v2_defines_entity_whitelist_and_canonical_values():
    from app.domains.chat.graph.business_understanding.prompt import (
        BUSINESS_UNDERSTANDING_SYSTEM_PROMPT,
    )

    for field in [
        "operation_plan_no", "train_no", "formation_no", "contract_no",
        "document_type", "document_no", "customer", "supplier", "coal_type",
        "departure_station", "arrival_station", "railway_section", "time_range",
        "data_version", "metric_name", "exception_description",
    ]:
        assert field in BUSINESS_UNDERSTANDING_SYSTEM_PROMPT
    for token in [
        "货运运单统一填写为运单",
        "station、date、time、metric、topic、concept",
        "不得创建白名单之外的字段",
    ]:
        assert token in BUSINESS_UNDERSTANDING_SYSTEM_PROMPT
