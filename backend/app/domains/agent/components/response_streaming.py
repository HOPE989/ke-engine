"""Agent 响应流式输出组件。"""

from collections.abc import Iterable


def iter_text_chunks(text: str) -> Iterable[str]:
    """返回单段文本流，后续可替换为真正 token stream。"""

    yield text
