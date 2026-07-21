"""业务理解结构化输出节点。"""

from langgraph.runtime import Runtime

from app.domains.chat.graph.business_understanding import BusinessUnderstandingResult
from app.domains.chat.graph.business_understanding.prompt import (
    build_business_understanding_messages,
)
from app.domains.chat.graph.context import ChatRuntimeContext
from app.domains.chat.graph.state import ChatState


async def business_understanding_node(
    state: ChatState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict[str, BusinessUnderstandingResult]:
    """基于完整会话历史产出一次业务理解结果。"""

    structured_model = runtime.context.model.with_structured_output(
        BusinessUnderstandingResult
    )
    result = await structured_model.ainvoke(
        build_business_understanding_messages(state["messages"])
    )
    return {"business_understanding": result}
