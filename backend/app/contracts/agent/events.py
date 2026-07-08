"""Agent 事件契约。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentMessageCreated:
    """Agent 消息创建事件。"""

    conversation_id: str
    message_id: str
