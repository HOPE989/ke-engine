"""Chat LLM 节点。"""

from langchain_core.messages import BaseMessage
from langgraph.runtime import Runtime

from app.domains.chat.graph.context import ChatRuntimeContext
from app.domains.chat.graph.state import ChatState


async def llm_node(
    state: ChatState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict[str, list[BaseMessage]]:
    """调用应用注入的模型，并返回单条 AI message update。"""

    message = await runtime.context.model.ainvoke(state["messages"])
    return {"messages": [message]}
