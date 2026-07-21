"""通过 LangGraph interrupt 挂起并恢复业务澄清。"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.types import interrupt

from app.domains.chat.graph.business_understanding import (
    ClarificationInterruptPayload,
)
from app.domains.chat.graph.state import ChatState


def clarify_node(state: ChatState) -> dict[str, list[BaseMessage]]:
    """挂起澄清，恢复后把问题和有效回答原子加入消息状态。"""

    result = state["business_understanding"]
    payload = ClarificationInterruptPayload(
        question=result.clarification_question or ""
    )
    resumed_content = interrupt(payload.model_dump(mode="json"))
    if not isinstance(resumed_content, str) or not resumed_content.strip():
        raise ValueError("clarification resume content must be non-blank text")
    return {
        "messages": [
            AIMessage(content=payload.question),
            HumanMessage(content=resumed_content.strip()),
        ]
    }
