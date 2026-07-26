"""声明完整 RAG 管线当前已实现的拓扑。"""

from collections.abc import Collection
from functools import partial

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.domains.rag.graph.nodes.query_router import query_router_node
from app.domains.rag.graph.nodes.query_rewrite import query_rewrite_node
from app.domains.rag.graph.query_router import RetrieverKind
from app.domains.rag.graph.state import RagState


QUERY_REWRITE_NODE = "query_rewrite"
QUERY_ROUTER_NODE = "query_router"


def build_rag_graph(
    *,
    model: BaseChatModel,
    available_retrievers: Collection[RetrieverKind],
) -> StateGraph:
    """构建 RAG Graph；后续阶段继续向同一拓扑追加节点。"""

    available = frozenset(
        RetrieverKind(retriever) for retriever in available_retrievers
    )
    if not available:
        raise ValueError("available_retrievers must not be empty")
    ordered_available = tuple(
        retriever
        for retriever in RetrieverKind
        if retriever in available
    )

    graph = StateGraph(RagState)
    graph.add_node(
        QUERY_REWRITE_NODE,
        partial(query_rewrite_node, model=model),
    )
    graph.add_node(
        QUERY_ROUTER_NODE,
        partial(
            query_router_node,
            model=model,
            available_retrievers=ordered_available,
        ),
    )
    graph.add_edge(START, QUERY_REWRITE_NODE)
    graph.add_edge(QUERY_REWRITE_NODE, QUERY_ROUTER_NODE)
    graph.add_edge(QUERY_ROUTER_NODE, END)
    return graph
