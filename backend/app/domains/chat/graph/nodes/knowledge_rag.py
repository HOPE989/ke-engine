"""通过 runtime 注入的 RagClient 获取文档证据。"""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from app.domains.chat.graph.business_understanding import (
    BusinessUnderstandingResult,
)
from app.domains.chat.graph.context import ChatRuntimeContext
from app.domains.chat.graph.state import ChatState
from app.domains.chat.services.rag import RagClient
from app.domains.rag.services import RetrieveEvidenceRequest


async def knowledge_rag_node(
    state: ChatState,
    runtime: Runtime[ChatRuntimeContext],
) -> dict[str, object]:
    return await invoke_knowledge_rag(
        state,
        rag_client=runtime.context.rag_client,
        user_id=runtime.context.user_id,
    )


async def invoke_knowledge_rag(
    state: ChatState,
    *,
    rag_client: RagClient | None,
    user_id: str | None,
) -> dict[str, object]:
    """构造最小 MCP 请求并把公开结果写回可序列化 state。"""

    if rag_client is None or user_id is None or not user_id.strip():
        raise RuntimeError("RagClient and user_id are required")
    messages = state["messages"]
    current_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], HumanMessage)
        ),
        None,
    )
    if current_index is None:
        raise ValueError("knowledge RAG requires a current user message")
    current = messages[current_index]
    if not isinstance(current.content, str) or not current.content.strip():
        raise ValueError("knowledge RAG requires text user content")

    understanding = BusinessUnderstandingResult.model_validate(
        state["business_understanding"]
    )
    if understanding.intent is None:
        raise ValueError("knowledge RAG requires a business intent")

    history = [
        {
            "role": "user" if isinstance(message, HumanMessage) else "assistant",
            "content": message.content,
        }
        for message in messages[:current_index]
        if isinstance(message, (HumanMessage, AIMessage))
        and isinstance(message.content, str)
        and message.content.strip()
    ][-10:]
    package = await rag_client.retrieve_evidence(
        RetrieveEvidenceRequest.model_validate(
            {
                "query": current.content,
                "accessibleBy": [user_id],
                "conversationContext": history,
                "businessIntent": understanding.intent.value,
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
