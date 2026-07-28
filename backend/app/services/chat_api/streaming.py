"""把 LangGraph 内部事件投影为应用拥有的稳定 SSE 协议。

transport 不直接序列化框架事件，以免把 run ID、tags、metadata 等内部结构暴露给
客户端。本模块也不生成 SSE id、retry、heartbeat 或 replay 数据。
"""

import json
from collections.abc import Sequence

from langchain_core.messages import AIMessage, AIMessageChunk
from pydantic import BaseModel, ValidationError

from app.contracts.chat.stream import (
    ContentDeltaPayload,
    RagEvidenceItemPayload,
    RagEvidencePayload,
    TraceStepPayload,
)
from app.domains.chat.graph.business_understanding import ClarificationInterruptPayload
from app.domains.chat.graph.nodes.grounded_answer import EMPTY_EVIDENCE_ANSWER
from app.domains.chat.graph.routing import (
    BUSINESS_RAG_NODE,
    BUSINESS_UNDERSTANDING_NODE,
    CLARIFY_NODE,
    CONTEXTUALIZE_QUERY_NODE,
    GROUNDED_ANSWER_NODE,
    LLM_NODE,
)
from app.domains.rag.services import EvidencePackage


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


TRACEABLE_NODES = {
    BUSINESS_UNDERSTANDING_NODE,
    CONTEXTUALIZE_QUERY_NODE,
    BUSINESS_RAG_NODE,
    GROUNDED_ANSWER_NODE,
    LLM_NODE,
    CLARIFY_NODE,
}


def project_trace_step(
    event: dict[str, object],
) -> TraceStepPayload | None:
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        return None
    node = metadata.get("langgraph_node")
    if not isinstance(node, str) or node not in TRACEABLE_NODES:
        return None
    status = {
        "on_chain_start": "started",
        "on_chain_end": "completed",
    }.get(event.get("event"))
    if status is None:
        return None
    return TraceStepPayload(node=node, status=status)


def project_rag_evidence(
    event: dict[str, object],
) -> RagEvidencePayload | None:
    metadata = event.get("metadata")
    if (
        event.get("event") != "on_chain_stream"
        or not isinstance(metadata, dict)
        or metadata.get("langgraph_node") != BUSINESS_RAG_NODE
    ):
        return None
    data = event.get("data")
    chunk = data.get("chunk") if isinstance(data, dict) else None
    raw_package = (
        chunk.get("evidence_package") if isinstance(chunk, dict) else None
    )
    if raw_package is None:
        return None
    package = EvidencePackage.model_validate(raw_package)
    return RagEvidencePayload(
        standalone_query=package.query,
        selected_retrievers=tuple(package.selected_retrievers),
        evidence_items=tuple(
            RagEvidenceItemPayload.model_validate(
                item.model_dump(mode="json")
            )
            for item in package.evidence_items
        ),
    )


def project_empty_evidence_event(
    event: dict[str, object],
) -> ContentDeltaPayload | None:
    """只投影 grounded_answer 的确定性空证据消息。"""

    metadata = event.get("metadata")
    if (
        event.get("event") != "on_chain_stream"
        or not isinstance(metadata, dict)
        or metadata.get("langgraph_node") != GROUNDED_ANSWER_NODE
    ):
        return None
    data = event.get("data")
    chunk = data.get("chunk") if isinstance(data, dict) else None
    messages = chunk.get("messages") if isinstance(chunk, dict) else None
    if not isinstance(messages, list) or len(messages) != 1:
        return None
    message = messages[0]
    if type(message) is not AIMessage or message.content != EMPTY_EVIDENCE_ANSWER:
        return None
    return ContentDeltaPayload(content=EMPTY_EVIDENCE_ANSWER)


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
