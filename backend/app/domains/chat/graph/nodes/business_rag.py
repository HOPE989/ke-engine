"""把 Chat 已上下文化的问题交给无状态 RAG MCP。"""

from langgraph.runtime import Runtime

from app.domains.chat.graph.context import ChatRuntimeContext
from app.domains.chat.graph.state import ChatState
from app.domains.chat.services.rag import RagClient
from app.domains.rag.services import RetrieveEvidenceRequest


async def business_rag_node(
    state: ChatState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict[str, object]:
    return await invoke_business_rag(
        state,
        rag_client=runtime.context.rag_client,
        user_id=runtime.context.user_id,
    )


async def invoke_business_rag(
    state: ChatState,
    *,
    rag_client: RagClient | None,
    user_id: str | None,
) -> dict[str, object]:
    if rag_client is None or user_id is None or not user_id.strip():
        raise RuntimeError("RagClient and user_id are required")
    standalone_query = state.get("standalone_query")
    if not isinstance(standalone_query, str) or not standalone_query.strip():
        raise ValueError("business RAG requires a standalone query")

    package = await rag_client.retrieve_evidence(
        RetrieveEvidenceRequest.model_validate(
            {
                "query": standalone_query,
                "accessibleBy": [user_id],
            }
        )
    )
    evidence = package.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )
    references = [
        {
            key: item[key]
            for key in (
                "sourceType",
                "citationId",
                "docId",
                "chunkId",
                "fileName",
                "url",
                "rerankScore",
            )
            if key in item
        }
        for item in evidence["evidenceItems"]
    ]
    return {
        "evidence_package": evidence,
        "rag_references": references,
    }
