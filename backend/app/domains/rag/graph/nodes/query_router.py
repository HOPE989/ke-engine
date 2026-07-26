from collections.abc import Collection, Mapping

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.domains.rag.graph.query_router import (
    QueryRouteResult,
    QueryRouterInput,
    QueryRouterUnavailable,
    RetrievalPlan,
    RetrieverKind,
    RoutingDecisionSource,
)
from app.domains.rag.graph.query_router.prompt import (
    build_query_router_messages,
)
from app.domains.rag.graph.state import RagState


async def query_router_node(
    state: RagState,
    *,
    model: BaseChatModel,
    retriever_destinations: Mapping[RetrieverKind, str],
    config: RunnableConfig | None = None,
) -> Command:
    """生成检索计划，并原子更新 state 后跳转到已注册节点。"""

    request = QueryRouterInput.model_validate(
        {
            "standalone_query": state["standalone_query"],
            "available_retrievers": list(retriever_destinations),
        }
    )
    try:
        structured_model = model.with_structured_output(
            QueryRouteResult,
            method="json_mode",
        )
        raw_result = await structured_model.ainvoke(
            build_query_router_messages(request),
            config=config,
        )
        result = QueryRouteResult.model_validate(raw_result)
        selected = set(result.selected_retrievers)
        if not selected.issubset(request.available_retrievers):
            raise ValueError("model selected unavailable retriever")
        plan = RetrievalPlan(
            selected_retrievers=[
                retriever
                for retriever in RetrieverKind
                if retriever in selected
            ],
            routing_reason=result.routing_reason,
            decision_source=RoutingDecisionSource.MODEL,
        )
    except Exception as exc:
        plan = _fallback_plan(request.available_retrievers, cause=exc)

    return Command(
        update={"retrieval_plan": plan.model_dump(mode="json")},
        goto=[
            retriever_destinations[retriever]
            for retriever in plan.selected_retrievers
        ],
    )


def _fallback_plan(
    available_retrievers: Collection[RetrieverKind],
    *,
    cause: Exception,
) -> RetrievalPlan:
    if RetrieverKind.DOCUMENT_HYBRID not in available_retrievers:
        raise QueryRouterUnavailable(
            "query router unavailable"
        ) from cause
    return RetrievalPlan(
        selected_retrievers=[RetrieverKind.DOCUMENT_HYBRID],
        routing_reason="路由不可用，使用文档混合检索",
        decision_source=RoutingDecisionSource.FALLBACK,
    )
