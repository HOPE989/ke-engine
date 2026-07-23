"""完整 RAG 管线在单次请求内共享的可序列化状态。"""

from typing import NotRequired, Required, TypedDict

from app.domains.rag.graph.query_rewrite import (
    QueryRewriteFailureCode,
    QueryRewriteStatus,
)


class RagState(TypedDict, total=False):
    """按已落地阶段增量扩展；当前只声明 Query Rewrite 所需字段。"""

    original_query: Required[str]
    conversation_context: NotRequired[list[dict[str, str]]]
    business_context: NotRequired[dict[str, object] | None]
    standalone_query: NotRequired[str]
    rewrite_status: NotRequired[QueryRewriteStatus]
    rewrite_failure_code: NotRequired[QueryRewriteFailureCode | None]
    warnings: NotRequired[list[str]]
