"""一次 RAG Graph 运行所需、但不进入 state 的依赖。"""

from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel


@dataclass(frozen=True, slots=True)
class RagRuntimeContext:
    model: BaseChatModel
