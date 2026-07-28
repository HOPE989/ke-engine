"""执行请求级 LangChain Elasticsearch Hybrid Retriever。"""

import asyncio
from time import perf_counter
from typing import Any

from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig

from app.domains.rag.graph.query_router import RetrieverKind
from app.domains.rag.graph.retrieval import (
    DocumentCandidate,
    DocumentRetrievalOptions,
    DocumentRetrievalScope,
    RetrievalDiagnostics,
    RetrievalOutcome,
    RetrievalStatus,
)
from app.domains.rag.graph.state import RagState

_SOURCE_METADATA_KEYS = frozenset(
    {
        "documentCreatedAt",
        "fileName",
        "mimeType",
        "matchedChunkId",
        "pageNumber",
        "section",
        "title",
        "url",
    }
)


async def document_hybrid_node(
    state: RagState,
    *,
    retriever_factory: Any,
    options: DocumentRetrievalOptions,
    config: RunnableConfig | None = None,
) -> dict[str, dict[str, dict[str, object]]]:
    """调用标准 Retriever，并把结果转换为可序列化 outcome。"""

    query = state["standalone_query"]
    if not isinstance(query, str) or not query.strip():
        raise ValueError("standalone_query must be non-blank")
    scope = DocumentRetrievalScope.model_validate(
        state.get("document_retrieval_scope")
    )
    started = perf_counter()
    try:
        retriever = retriever_factory.create(scope)
        async with asyncio.timeout(options.timeout_seconds):
            documents = await retriever.ainvoke(query.strip(), config=config)
        stages = getattr(retriever, "retrieval_stages", None)
        candidates = tuple(
            _document_candidate(document) for document in documents
        )
        status = (
            RetrievalStatus.SUCCESS
            if candidates
            else RetrievalStatus.EMPTY
        )
    except Exception:
        stages = None
        candidates = ()
        status = RetrievalStatus.FAILED

    outcome = RetrievalOutcome(
        retriever_id=RetrieverKind.DOCUMENT_HYBRID,
        status=status,
        candidates=candidates,
        diagnostics=RetrievalDiagnostics(
            duration_ms=_elapsed_ms(started),
            result_count=len(candidates),
            stages=stages,
        ),
    )
    return {
        "retrieval_outcomes": {
            RetrieverKind.DOCUMENT_HYBRID.value: outcome.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            )
        }
    }


def _document_candidate(document: Document) -> DocumentCandidate:
    metadata = document.metadata
    source_metadata = {
        key: metadata[key]
        for key in sorted(_SOURCE_METADATA_KEYS)
        if key in metadata
    }
    candidate = {
        "chunkId": str(metadata.get("chunkId", "")),
        "docId": str(metadata.get("docId", "")),
        "text": document.page_content,
        "sourceMetadata": source_metadata,
    }
    if "rerankScore" in metadata:
        candidate["rerankScore"] = metadata["rerankScore"]
    return DocumentCandidate.model_validate(candidate)


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
