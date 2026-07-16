"""一次 Chat Graph 运行所需、但不写入 checkpoint 的依赖上下文。"""

from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel


@dataclass(frozen=True, slots=True)
class ChatRuntimeContext:
    """由应用生命周期注入 Graph 的运行依赖。

    模型放在 runtime context 而非 state 中，避免不可序列化的客户端对象进入
    checkpoint，也使测试可以为每次运行注入确定性的 fake model。
    """

    model: BaseChatModel
