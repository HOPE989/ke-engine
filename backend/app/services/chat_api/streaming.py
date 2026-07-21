"""把 LangGraph 内部事件投影为应用拥有的稳定 SSE 协议。

transport 不直接序列化框架事件，以免把 run ID、tags、metadata 等内部结构暴露给
客户端。本模块也不生成 SSE id、retry、heartbeat 或 replay 数据。
"""

import json
from collections.abc import Sequence

from langchain_core.messages import AIMessage, AIMessageChunk
from pydantic import BaseModel, ValidationError

from app.contracts.chat.stream import ContentDeltaPayload
from app.domains.chat.graph.business_understanding import ClarificationInterruptPayload
from app.domains.chat.graph.nodes.business_boundary import BUSINESS_BOUNDARY_MESSAGE
from app.domains.chat.graph.routing import BUSINESS_BOUNDARY_NODE


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


def project_business_boundary_event(
    event: dict[str, object],
) -> ContentDeltaPayload | None:
    """投影确定性 BUSINESS 边界节点的唯一公开消息更新。"""

    metadata = event.get("metadata")
    if (
        event.get("event") != "on_chain_stream"
        or not isinstance(metadata, dict)
        or metadata.get("langgraph_node") != BUSINESS_BOUNDARY_NODE
    ):
        return None

    data = event.get("data")
    chunk = data.get("chunk") if isinstance(data, dict) else None
    messages = chunk.get("messages") if isinstance(chunk, dict) else None
    if not isinstance(messages, list) or len(messages) != 1:
        raise ValueError("unsupported business boundary event")

    message = messages[0]
    if not isinstance(message, AIMessage) or message.content != BUSINESS_BOUNDARY_MESSAGE:
        raise ValueError("unsupported business boundary event")
    return ContentDeltaPayload(content=BUSINESS_BOUNDARY_MESSAGE)


def project_clarification_interrupt(
    event: dict[str, object],
) -> ClarificationInterruptPayload | None:
    """投影受支持的 LangGraph 澄清中断，且不泄露框架内部字段。"""

    if event.get("event") != "on_chain_stream":
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    chunk = data.get("chunk")
    if not isinstance(chunk, dict) or "__interrupt__" not in chunk:
        return None

    interrupts = chunk["__interrupt__"]
    if (
        isinstance(interrupts, (str, bytes))
        or not isinstance(interrupts, Sequence)
        or len(interrupts) != 1
    ):
        raise ValueError("unsupported clarification interrupt")

    interrupt = interrupts[0]
    if not hasattr(interrupt, "value"):
        raise ValueError("unsupported clarification interrupt")

    try:
        return ClarificationInterruptPayload.model_validate(interrupt.value)
    except ValidationError as exc:
        raise ValueError("unsupported clarification interrupt") from exc
