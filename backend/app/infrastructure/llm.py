"""LLM 基础设施入口。"""

from app.domains.agent.services.chat import get_chat_model

__all__ = ["get_chat_model"]
