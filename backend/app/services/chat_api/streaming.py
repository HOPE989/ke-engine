"""LangGraph 事件到应用 SSE 协议的投影。"""

import json

from langchain_core.messages import AIMessageChunk
from pydantic import BaseModel

from app.contracts.chat.stream import ContentDeltaPayload


def encode_sse(event: str, payload: BaseModel) -> bytes:
    """编码一个不带 id/retry 的 SSE event/data 帧。"""

    data = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: {event}\ndata: {data}\n\n".encode()


def project_graph_event(event: dict[str, object]) -> ContentDeltaPayload | None:
    """只投影公开的 assistant 文本增量。"""

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
