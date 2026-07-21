"""业务请求在业务检索接入前的确定性边界节点。"""

from langchain_core.messages import AIMessage

from app.domains.chat.graph.state import ChatState

BUSINESS_BOUNDARY_MESSAGE = "已识别业务请求，但当前阶段尚未连接业务检索。"


def business_boundary_node(state: ChatState) -> dict[str, list[AIMessage]]:
    """返回业务检索尚未接入的固定说明。"""

    return {"messages": [AIMessage(content=BUSINESS_BOUNDARY_MESSAGE)]}
