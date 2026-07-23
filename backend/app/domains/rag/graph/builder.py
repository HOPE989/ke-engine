"""声明完整 RAG 管线当前已实现的拓扑。"""

from functools import partial

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.domains.rag.graph.nodes.query_rewrite import query_rewrite_node
from app.domains.rag.graph.state import RagState


QUERY_REWRITE_NODE = "query_rewrite"


def build_rag_graph(
    *,
    model: BaseChatModel,
) -> StateGraph:
    """构建 RAG Graph；后续阶段继续向同一拓扑追加节点。"""

    graph = StateGraph(RagState)
    graph.add_node(
        QUERY_REWRITE_NODE,
        partial(query_rewrite_node, model=model),
    )
    graph.add_edge(START, QUERY_REWRITE_NODE)
    graph.add_edge(QUERY_REWRITE_NODE, END)
    return graph
