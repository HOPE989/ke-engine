"""Chat Graph 的业务理解路由原语。"""

from typing import Literal

from app.domains.chat.graph.business_understanding import BusinessRoute
from app.domains.chat.graph.state import ChatState

BUSINESS_UNDERSTANDING_NODE = "business_understanding"
BUSINESS_BOUNDARY_NODE = "business_boundary"
CLARIFY_NODE = "clarify"
LLM_NODE = "llm"


def route_business_understanding(
    state: ChatState,
) -> Literal["llm", "business_boundary", "clarify"]:
    """根据已持久化的业务理解结果选择后续节点。"""

    result = state["business_understanding"]
    return {
        BusinessRoute.NON_BUSINESS: LLM_NODE,
        BusinessRoute.BUSINESS: BUSINESS_BOUNDARY_NODE,
        BusinessRoute.CLARIFY: CLARIFY_NODE,
    }[result.route]
