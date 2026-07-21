"""业务理解 fixture 与 Langfuse Dataset Experiment 之间的薄适配层。"""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID, uuid5

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langfuse import Evaluation
from langgraph.runtime import Runtime

from app.domains.chat.graph.business_understanding import (
    BusinessIntent,
    BusinessRoute,
)
from app.domains.chat.graph.business_understanding.evaluation import (
    EvaluationCase,
    score_evaluation_cases,
)
from app.domains.chat.graph.business_understanding.prompt import (
    BUSINESS_UNDERSTANDING_PROMPT_VERSION,
)
from app.domains.chat.graph.context import ChatRuntimeContext
from app.domains.chat.graph.nodes.business_understanding import (
    business_understanding_node,
)


DATASET_NAME = "ke-engine/business-understanding-v1"
DATASET_ITEM_NAMESPACE = UUID("a4b20d75-e25d-4c07-8930-d6954ee86318")


def dataset_item_id(case: EvaluationCase) -> str:
    """为 project 内的 fixture case 生成可重复 upsert 的 Dataset item ID。"""

    return uuid5(DATASET_ITEM_NAMESPACE, f"{DATASET_NAME}:{case.id}").hex


def dataset_item_payload(case: EvaluationCase) -> dict[str, Any]:
    """完整保留一个本地标注 case 的 Dataset input、期望值和检索元数据。"""

    return {
        "id": dataset_item_id(case),
        "input": {"messages": case.messages},
        "expected_output": {
            "route": case.expected_route.value,
            "intent": (
                case.expected_intent.value
                if case.expected_intent is not None
                else None
            ),
            "key_entities": case.expected_key_entities,
            "clarification_contains": case.expected_clarification_contains,
        },
        "metadata": {
            "case_id": case.id,
            "category": case.category,
            "prompt_version": BUSINESS_UNDERSTANDING_PROMPT_VERSION,
        },
    }


def langfuse_evaluator(
    *,
    input: Mapping[str, Any],
    output: Mapping[str, Any],
    expected_output: Mapping[str, Any],
    metadata: Mapping[str, Any],
    **_: Any,
) -> list[Evaluation]:
    """把现有五维确定性 scorer 结果转换成 Langfuse numeric evaluations。"""

    case = _evaluation_case_from_langfuse(
        input=input,
        expected_output=expected_output,
        metadata=metadata,
    )
    score = score_evaluation_cases(case, output)
    dimensions = {
        "route_accuracy": score.route,
        "intent_accuracy": score.intent,
        "key_entity_recall": score.key_entities,
        "clarification_accuracy": score.clarification,
        "schema_validity": score.schema_validity,
    }
    return [
        Evaluation(
            name=name,
            value=_ratio(value),
            comment=f"{value[0]}/{value[1]}",
            data_type="NUMERIC",
        )
        for name, value in dimensions.items()
    ]


async def run_business_understanding_case(
    *,
    item: Any,
    model: BaseChatModel,
) -> dict[str, Any]:
    """使用完整 Dataset 消息历史执行生产业务理解节点。"""

    messages = langchain_messages(item.input["messages"])
    command = await business_understanding_node(
        {"messages": messages},
        Runtime(context=ChatRuntimeContext(model=model)),
    )
    result = command.update["business_understanding"]
    return result.model_dump(mode="json")


def langchain_messages(messages: Sequence[Mapping[str, str]]) -> list[BaseMessage]:
    """把 Dataset 的角色消息转换为 LangChain 消息，并保留原始顺序与内容。"""

    message_types = {
        "user": HumanMessage,
        "assistant": AIMessage,
        "system": SystemMessage,
    }
    converted: list[BaseMessage] = []
    for message in messages:
        role = message["role"]
        try:
            message_type = message_types[role]
        except KeyError as exc:
            raise ValueError(f"unsupported evaluation message role: {role}") from exc
        converted.append(message_type(content=message["content"]))
    return converted


def _evaluation_case_from_langfuse(
    *,
    input: Mapping[str, Any],
    expected_output: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> EvaluationCase:
    intent = expected_output.get("intent")
    return EvaluationCase(
        id=str(metadata["case_id"]),
        category=str(metadata["category"]),
        messages=[dict(message) for message in input["messages"]],
        expected_route=BusinessRoute(expected_output["route"]),
        expected_intent=BusinessIntent(intent) if intent is not None else None,
        expected_key_entities=dict(expected_output.get("key_entities") or {}),
        expected_clarification_contains=expected_output.get(
            "clarification_contains"
        ),
    )


def _ratio(value: tuple[int, int]) -> float:
    hits, total = value
    return hits / total if total else 1.0
