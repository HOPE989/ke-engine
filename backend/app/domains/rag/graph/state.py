"""一次 Query Rewrite Graph 运行的可序列化状态。"""

from typing import NotRequired, Required, TypedDict

from app.domains.rag.graph.query_rewrite import (
    QueryRewriteFailureCode,
    QueryRewriteStatus,
)


class RagQueryRewriteState(TypedDict, total=False):
    original_query: Required[str]
    conversation_context: NotRequired[list[dict[str, str]]]
    business_context: NotRequired[dict[str, object] | None]
    standalone_query: NotRequired[str]
    rewrite_status: NotRequired[QueryRewriteStatus]
    rewrite_failure_code: NotRequired[QueryRewriteFailureCode | None]
    warnings: NotRequired[list[str]]
