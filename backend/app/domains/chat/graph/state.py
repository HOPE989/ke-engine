"""Chat Graph state。"""

from langgraph.graph import MessagesState


class ChatState(MessagesState):
    """使用 LangGraph message reducer 的 Chat state。"""
