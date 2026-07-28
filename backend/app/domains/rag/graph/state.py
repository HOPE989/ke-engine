"""完整 RAG 管线在单次请求内共享的可序列化状态。"""

from typing import Annotated, NotRequired, Required, TypedDict

from app.domains.rag.graph.retrieval.reducer import (
    merge_retrieval_outcomes,
)


class RagState(TypedDict, total=False):
    """按已落地阶段增量扩展的请求级 RAG 状态。"""

    standalone_query: Required[str]
    retrieval_plan: NotRequired[dict[str, object]]
    document_retrieval_scope: NotRequired[dict[str, object]]
    retrieval_outcomes: Annotated[
        dict[str, dict[str, object]],
        merge_retrieval_outcomes,
    ]
