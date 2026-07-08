"""Agent 上下文构造组件。"""


def build_context(messages: list[str]) -> str:
    """把消息列表拼接为上下文文本。"""

    return "\n".join(message for message in messages if message.strip())
