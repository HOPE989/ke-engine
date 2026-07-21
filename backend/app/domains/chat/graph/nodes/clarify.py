"""通过 LangGraph interrupt 挂起并恢复业务澄清。"""

from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.types import Command, interrupt

from app.domains.chat.graph.business_understanding import (
    ClarificationInterruptPayload,
)
from app.domains.chat.graph.routing import BUSINESS_UNDERSTANDING_NODE
from app.domains.chat.graph.state import ChatState


def clarify_node(
    state: ChatState,
) -> Command[Literal["business_understanding"]]:
    """挂起澄清，恢复后把问题和有效回答原子加入消息状态。"""

    result = state["business_understanding"]
    payload = ClarificationInterruptPayload(
        question=result.clarification_question or ""
    )
    resumed_content = interrupt(payload.model_dump(mode="json"))
    if not isinstance(resumed_content, str) or not resumed_content.strip():
        raise ValueError("clarification resume content must be non-blank text")
    messages: list[BaseMessage] = [
        AIMessage(content=payload.question),
        HumanMessage(content=resumed_content.strip()),
    ]
    return Command(
        update={"messages": messages},
        goto=BUSINESS_UNDERSTANDING_NODE,
    )
