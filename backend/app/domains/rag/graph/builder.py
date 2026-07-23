"""声明完整 RAG 管线当前已实现的拓扑。"""

from functools import partial

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.domains.rag.graph.context import RagRuntimeContext
from app.domains.rag.graph.nodes.query_rewrite import (
    invoke_query_rewrite,
    query_rewrite_node,
)
from app.domains.rag.graph.state import RagState


QUERY_REWRITE_NODE = "query_rewrite"


def build_rag_graph(
    *,
    bound_model: BaseChatModel | None = None,
) -> StateGraph:
    """构建 RAG Graph；后续阶段继续向同一拓扑追加节点。"""

    context_schema = RagRuntimeContext if bound_model is None else None
    node = (
        query_rewrite_node
        if bound_model is None
        else partial(invoke_query_rewrite, model=bound_model)
    )
    graph = StateGraph(
        RagState,
        context_schema=context_schema,
    )
    graph.add_node(QUERY_REWRITE_NODE, node)
    graph.add_edge(START, QUERY_REWRITE_NODE)
    graph.add_edge(QUERY_REWRITE_NODE, END)
    return graph
