"""Query Rewrite LangGraph 节点执行逻辑。"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from app.domains.rag.graph.query_rewrite import (
    QueryRewriteInput,
    QueryRewriteResult,
    QueryRewriteUpdate,
)
from app.domains.rag.graph.query_rewrite.prompt import (
    build_query_rewrite_messages,
)
from app.domains.rag.graph.state import RagState


async def query_rewrite_node(
    state: RagState,
    *,
    model: BaseChatModel,
    config: RunnableConfig | None = None,
) -> QueryRewriteUpdate:
    """使用装配期绑定的模型执行一次 Query Rewrite。"""

    request = QueryRewriteInput.model_validate(
        {
            "original_query": state["original_query"],
            "conversation_context": state.get("conversation_context", []),
            "business_context": state.get("business_context"),
        }
    )
    try:
        structured_model = model.with_structured_output(QueryRewriteResult)
        raw_result = await structured_model.ainvoke(
            build_query_rewrite_messages(request),
            config=config,
        )
    except Exception:
        return _fallback(request.original_query)

    try:
        result = QueryRewriteResult.model_validate(raw_result)
    except ValidationError:
        return _fallback(request.original_query)

    return {"standalone_query": result.standalone_query}


def _fallback(
    original_query: str,
) -> QueryRewriteUpdate:
    return {"standalone_query": original_query}
