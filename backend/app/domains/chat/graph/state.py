"""Chat Graph 可由 checkpointer 持久化的会话状态。"""

from langgraph.graph import MessagesState


class ChatState(MessagesState):
    """使用 LangGraph message reducer 合并每个节点返回的消息 update。

    state 只保存 Graph 推理上下文；面向用户的会话列表和消息历史仍以业务表为准。
    """
