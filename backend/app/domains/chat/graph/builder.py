"""声明带业务理解三路分支的生产 Chat Graph 拓扑。"""

from functools import partial

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.domains.chat.graph.context import ChatRuntimeContext
from app.domains.chat.graph.nodes.business_understanding import (
    business_understanding_node,
    invoke_business_understanding,
)
from app.domains.chat.graph.nodes.clarify import clarify_node
from app.domains.chat.graph.nodes.contextualize_query import (
    contextualize_query_node,
    invoke_contextualize_query,
)
from app.domains.chat.graph.nodes.llm import invoke_llm, llm_node
from app.domains.chat.graph.nodes.grounded_answer import (
    grounded_answer_node,
    invoke_grounded_answer,
)
from app.domains.chat.graph.nodes.business_rag import (
    business_rag_node,
    invoke_business_rag,
)
from app.domains.chat.graph.routing import (
    BUSINESS_RAG_NODE,
    BUSINESS_UNDERSTANDING_NODE,
    CLARIFY_NODE,
    CONTEXTUALIZE_QUERY_NODE,
    GROUNDED_ANSWER_NODE,
    LLM_NODE,
)
from app.domains.chat.services.rag import RagClient
from app.domains.chat.graph.state import ChatState


def build_chat_graph(
    *,
    bound_model: BaseChatModel | None = None,
    bound_rag_client: RagClient | None = None,
    bound_user_id: str | None = None,
) -> StateGraph:
    """声明业务理解三路拓扑，但不在领域层编译 Graph。

    编译需要生命周期内就绪的 PostgreSQL saver，因此由 Chat API 装配层完成。builder
    不创建模型、不读取 settings，也不为任何节点配置自动重试。
    """

    # 生产模式通过 runtime context 注入模型；Studio 仅预绑定开发模型。节点名与全部
    # 边仍只在本函数声明，因此两种入口不会产生两套拓扑。
    context_schema = ChatRuntimeContext if bound_model is None else None
    understanding = (
        business_understanding_node
        if bound_model is None
        else partial(invoke_business_understanding, model=bound_model)
    )
    response = (
        llm_node if bound_model is None else partial(invoke_llm, model=bound_model)
    )
    contextualize = (
        contextualize_query_node
        if bound_model is None
        else partial(invoke_contextualize_query, model=bound_model)
    )
    business_rag = (
        business_rag_node
        if bound_model is None
        else partial(
            invoke_business_rag,
            rag_client=bound_rag_client,
            user_id=bound_user_id,
        )
    )
    grounded = (
        grounded_answer_node
        if bound_model is None
        else partial(invoke_grounded_answer, model=bound_model)
    )
    graph = StateGraph(ChatState, context_schema=context_schema)
    graph.add_node(BUSINESS_UNDERSTANDING_NODE, understanding)
    graph.add_node(LLM_NODE, response)
    graph.add_node(CLARIFY_NODE, clarify_node)
    graph.add_node(CONTEXTUALIZE_QUERY_NODE, contextualize)
    graph.add_node(BUSINESS_RAG_NODE, business_rag)
    graph.add_node(GROUNDED_ANSWER_NODE, grounded)
    graph.add_edge(START, BUSINESS_UNDERSTANDING_NODE)
    graph.add_edge(LLM_NODE, END)
    graph.add_edge(CONTEXTUALIZE_QUERY_NODE, BUSINESS_RAG_NODE)
    graph.add_edge(BUSINESS_RAG_NODE, GROUNDED_ANSWER_NODE)
    graph.add_edge(GROUNDED_ANSWER_NODE, END)
    return graph
