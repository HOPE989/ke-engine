"""Query Rewrite LangGraph 节点执行逻辑。"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.domains.rag.graph.context import RagRuntimeContext
from app.domains.rag.graph.query_rewrite import (
    QUERY_REWRITE_FALLBACK_WARNING,
    QueryRewriteFailureCode,
    QueryRewriteInput,
    QueryRewriteResult,
    QueryRewriteStatus,
    QueryRewriteUpdate,
)
from app.domains.rag.graph.query_rewrite.prompt import (
    build_query_rewrite_messages,
)
from app.domains.rag.graph.state import RagState


async def query_rewrite_node(
    state: RagState,
    config: RunnableConfig,
    runtime: Runtime[RagRuntimeContext],
) -> QueryRewriteUpdate:
    """从当前 Graph runtime 取得模型并执行 Query Rewrite。"""

    return await invoke_query_rewrite(
        state,
        model=runtime.context.model,
        config=config,
    )


async def invoke_query_rewrite(
    state: RagState,
    *,
    model: BaseChatModel,
    config: RunnableConfig | None = None,
) -> QueryRewriteUpdate:
    """使用显式模型执行一次 Query Rewrite，供 runtime 与测试共同复用。"""

    request = QueryRewriteInput.model_validate(
        {
            "original_query": state["original_query"],
            "conversation_context": state.get("conversation_context", []),
            "business_context": state.get("business_context"),
        }
    )
    existing_warnings = list(state.get("warnings", []))

    try:
        structured_model = model.with_structured_output(QueryRewriteResult)
        raw_result = await structured_model.ainvoke(
            build_query_rewrite_messages(request),
            config=config,
        )
    except ValidationError:
        return _fallback(
            request.original_query,
            existing_warnings,
            QueryRewriteFailureCode.INVALID_OUTPUT,
        )
    except Exception:
        return _fallback(
            request.original_query,
            existing_warnings,
            QueryRewriteFailureCode.MODEL_INVOCATION_FAILED,
        )

    try:
        result = QueryRewriteResult.model_validate(raw_result)
    except ValidationError:
        return _fallback(
            request.original_query,
            existing_warnings,
            QueryRewriteFailureCode.INVALID_OUTPUT,
        )

    return {
        "standalone_query": result.standalone_query,
        "rewrite_status": QueryRewriteStatus.REWRITTEN,
        "rewrite_failure_code": None,
        "warnings": existing_warnings,
    }


def _fallback(
    original_query: str,
    existing_warnings: list[str],
    failure_code: QueryRewriteFailureCode,
) -> QueryRewriteUpdate:
    return {
        "standalone_query": original_query,
        "rewrite_status": QueryRewriteStatus.FALLBACK,
        "rewrite_failure_code": failure_code,
        "warnings": [
            *existing_warnings,
            QUERY_REWRITE_FALLBACK_WARNING,
        ],
    }
