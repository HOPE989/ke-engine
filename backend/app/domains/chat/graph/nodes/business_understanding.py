"""业务理解结构化输出节点。"""

from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.runtime import Runtime
from langgraph.types import Command

from app.domains.chat.graph.business_understanding import (
    BusinessRoute,
    BusinessUnderstandingResult,
)
from app.domains.chat.graph.business_understanding.prompt import (
    build_business_understanding_messages,
)
from app.domains.chat.graph.context import ChatRuntimeContext
from app.domains.chat.graph.routing import (
    BUSINESS_BOUNDARY_NODE,
    CLARIFY_NODE,
    LLM_NODE,
)
from app.domains.chat.graph.state import ChatState


async def business_understanding_node(
    state: ChatState,
    runtime: Runtime[ChatRuntimeContext],
) -> Command[Literal["llm", "business_boundary", "clarify"]]:
    """产出业务理解结果，并把执行权交给结果对应的固定节点。"""

    return await invoke_business_understanding(state, model=runtime.context.model)


async def invoke_business_understanding(
    state: ChatState,
    *,
    model: BaseChatModel,
) -> Command[Literal["llm", "business_boundary", "clarify"]]:
    """使用显式模型执行业务理解，供 runtime context 与 Studio 共同复用。"""

    structured_model = model.with_structured_output(BusinessUnderstandingResult)
    result = await structured_model.ainvoke(
        build_business_understanding_messages(state["messages"])
    )
    target = {
        BusinessRoute.NON_BUSINESS: LLM_NODE,
        BusinessRoute.BUSINESS: BUSINESS_BOUNDARY_NODE,
        BusinessRoute.CLARIFY: CLARIFY_NODE,
    }[result.route]
    return Command(
        update={"business_understanding": result},
        goto=target,
    )
