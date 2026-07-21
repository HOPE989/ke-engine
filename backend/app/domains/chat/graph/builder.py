"""声明带业务理解三路分支的生产 Chat Graph 拓扑。"""

from langgraph.graph import END, START, StateGraph

from app.domains.chat.graph.context import ChatRuntimeContext
from app.domains.chat.graph.nodes.business_boundary import business_boundary_node
from app.domains.chat.graph.nodes.business_understanding import (
    business_understanding_node,
)
from app.domains.chat.graph.nodes.clarify import clarify_node
from app.domains.chat.graph.nodes.llm import llm_node
from app.domains.chat.graph.routing import (
    BUSINESS_BOUNDARY_NODE,
    BUSINESS_UNDERSTANDING_NODE,
    CLARIFY_NODE,
    LLM_NODE,
    route_business_understanding,
)
from app.domains.chat.graph.state import ChatState


def build_chat_graph() -> StateGraph:
    """声明业务理解三路拓扑，但不在领域层编译 Graph。

    编译需要生命周期内就绪的 PostgreSQL saver，因此由 Chat API 装配层完成。builder
    不创建模型、不读取 settings，也不为任何节点配置自动重试。
    """

    # 领域层只描述稳定拓扑；运行资源通过 context schema 和 compile 参数注入。
    graph = StateGraph(ChatState, context_schema=ChatRuntimeContext)
    graph.add_node(BUSINESS_UNDERSTANDING_NODE, business_understanding_node)
    graph.add_node(LLM_NODE, llm_node)
    graph.add_node(BUSINESS_BOUNDARY_NODE, business_boundary_node)
    graph.add_node(CLARIFY_NODE, clarify_node)
    graph.add_edge(START, BUSINESS_UNDERSTANDING_NODE)
    graph.add_conditional_edges(
        BUSINESS_UNDERSTANDING_NODE,
        route_business_understanding,
        {
            LLM_NODE: LLM_NODE,
            BUSINESS_BOUNDARY_NODE: BUSINESS_BOUNDARY_NODE,
            CLARIFY_NODE: CLARIFY_NODE,
        },
    )
    graph.add_edge(LLM_NODE, END)
    graph.add_edge(BUSINESS_BOUNDARY_NODE, END)
    graph.add_edge(CLARIFY_NODE, BUSINESS_UNDERSTANDING_NODE)
    return graph
