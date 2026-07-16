"""首版 Chat Graph 中唯一的模型调用节点。"""

from langchain_core.messages import BaseMessage
from langgraph.runtime import Runtime

from app.domains.chat.graph.context import ChatRuntimeContext
from app.domains.chat.graph.state import ChatState


async def llm_node(
    state: ChatState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict[str, list[BaseMessage]]:
    """把当前 state messages 交给注入模型，并返回单条 AI message update。

    节点不读取全局 settings、不创建模型，也不处理 SSE 或业务消息持久化；返回值由
    ``MessagesState`` reducer 合并并由 LangGraph checkpointer 管理 superstep 状态。
    """

    message = await runtime.context.model.ainvoke(state["messages"])
    return {"messages": [message]}
