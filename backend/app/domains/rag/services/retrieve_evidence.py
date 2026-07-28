"""调用现有 RAG Graph 并投影为文档 EvidencePackage。"""

from typing import Any

from app.domains.rag.graph.query_router import RetrieverKind
from app.domains.rag.graph.retrieval import (
    RetrievalOutcome,
    RetrievalStatus,
)
from app.domains.rag.services.models import (
    EvidenceItem,
    EvidencePackage,
    RetrieveEvidenceRequest,
)


class EvidenceRetrievalFailed(RuntimeError):
    """文档 RAG 没有成功完成，不能伪装成空结果。"""


class RetrieveEvidenceService:
    """对 checkpointer-free compiled graph 的窄应用服务封装。"""

    def __init__(self, graph: Any) -> None:
        self._graph = graph

    async def retrieve_evidence(
        self,
        request: RetrieveEvidenceRequest,
    ) -> EvidencePackage:
        graph_input: dict[str, object] = {
            "original_query": request.query,
            "conversation_context": [
                message.model_dump(mode="json")
                for message in request.conversation_context
            ],
            "business_context": (
                {"intent": request.business_intent}
                if request.business_intent is not None
                else None
            ),
            "document_retrieval_scope": {
                "accessibleBy": list(request.accessible_by),
                "docIds": list(request.doc_ids),
            },
        }
        try:
            state = await self._graph.ainvoke(graph_input)
            return _project_evidence(request, state)
        except EvidenceRetrievalFailed:
            raise
        except Exception as exc:
            raise EvidenceRetrievalFailed(
                "document evidence retrieval failed"
            ) from exc


def _project_evidence(
    request: RetrieveEvidenceRequest,
    state: object,
) -> EvidencePackage:
    if not isinstance(state, dict):
        raise EvidenceRetrievalFailed("document evidence retrieval failed")
    outcomes = state.get("retrieval_outcomes")
    if not isinstance(outcomes, dict):
        raise EvidenceRetrievalFailed("document evidence retrieval failed")
    raw_outcome = outcomes.get(RetrieverKind.DOCUMENT_HYBRID.value)
    try:
        outcome = RetrievalOutcome.model_validate(raw_outcome)
    except Exception as exc:
        raise EvidenceRetrievalFailed(
            "document evidence retrieval failed"
        ) from exc
    if outcome.status is RetrievalStatus.FAILED:
        raise EvidenceRetrievalFailed("document evidence retrieval failed")

    standalone_query = state.get("standalone_query")
    if not isinstance(standalone_query, str) or not standalone_query.strip():
        raise EvidenceRetrievalFailed("document evidence retrieval failed")

    items = tuple(
        EvidenceItem(
            citation_id=f"{candidate.doc_id}:{candidate.chunk_id}",
            content=candidate.text,
            doc_id=candidate.doc_id,
            chunk_id=candidate.chunk_id,
            file_name=_optional_source(candidate.source_metadata, "fileName"),
            url=_optional_source(candidate.source_metadata, "url"),
            rerank_score=candidate.rerank_score,
        )
        for candidate in outcome.candidates
    )
    return EvidencePackage(
        query=request.query,
        standalone_query=standalone_query.strip(),
        evidence_items=items,
    )


def _optional_source(
    metadata: dict[str, object],
    key: str,
) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value.strip() else None
