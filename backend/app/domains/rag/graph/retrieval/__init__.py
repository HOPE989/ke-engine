"""RAG Retriever 的请求、候选、结果和 reducer 契约。"""

from app.domains.rag.graph.retrieval.models import (
    DocumentCandidate,
    DocumentRetrievalOptions,
    DocumentRetrievalScope,
    RetrievalDiagnostics,
    RetrievalOutcome,
    RetrievalStatus,
)
from app.domains.rag.graph.retrieval.reducer import (
    merge_retrieval_outcomes,
)

__all__ = [
    "DocumentCandidate",
    "DocumentRetrievalOptions",
    "DocumentRetrievalScope",
    "RetrievalDiagnostics",
    "RetrievalOutcome",
    "RetrievalStatus",
    "merge_retrieval_outcomes",
]
