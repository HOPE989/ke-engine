"""把 LangGraph 内部事件投影为应用拥有的稳定 SSE 协议。

transport 不直接序列化框架事件，以免把 run ID、tags、metadata 等内部结构暴露给
客户端。本模块也不生成 SSE id、retry、heartbeat 或 replay 数据。
"""

import json

from langchain_core.messages import AIMessageChunk
from pydantic import BaseModel

from app.contracts.chat.stream import ContentDeltaPayload


def encode_sse(event: str, payload: BaseModel) -> bytes:
    """把应用事件编码为 UTF-8 SSE ``event``/``data`` 帧。

    JSON 使用紧凑格式但保留中文字符；返回 bytes 便于 ``StreamingResponse`` 直接
    发送。首版协议刻意不包含 ``id`` 和 ``retry`` 字段。
    """

    data = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: {event}\ndata: {data}\n\n".encode()


def project_graph_event(event: dict[str, object]) -> ContentDeltaPayload | None:
    """从 LangGraph 事件中提取公开的 ASSISTANT 文本增量。

    仅接受 ``on_chat_model_stream`` 的非空字符串 ``AIMessageChunk``；其他节点事件、
    结构异常和空 chunk 返回 ``None``，由调用方忽略。
    """

    if event.get("event") != "on_chat_model_stream":
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    chunk = data.get("chunk")
    if not isinstance(chunk, AIMessageChunk) or not isinstance(chunk.content, str):
        return None
    if not chunk.content:
        return None
    return ContentDeltaPayload(content=chunk.content)
