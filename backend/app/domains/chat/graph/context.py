"""Chat Graph runtime context。"""

from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel


@dataclass(frozen=True, slots=True)
class ChatRuntimeContext:
    """由应用生命周期注入 Graph 的运行依赖。"""

    model: BaseChatModel
