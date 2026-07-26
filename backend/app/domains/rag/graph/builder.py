"""声明完整 RAG 管线当前已实现的拓扑。"""

from functools import partial
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.domains.rag.graph.nodes.collect_retrieval_outcomes import (
    collect_retrieval_outcomes_node,
)
from app.domains.rag.graph.nodes.document_hybrid import (
    document_hybrid_node,
)
from app.domains.rag.graph.nodes.query_router import query_router_node
from app.domains.rag.graph.nodes.query_rewrite import query_rewrite_node
from app.domains.rag.graph.query_router import RetrieverKind
from app.domains.rag.graph.retrieval import DocumentRetrievalOptions
from app.domains.rag.graph.state import RagState


QUERY_REWRITE_NODE = "query_rewrite"
QUERY_ROUTER_NODE = "query_router"
DOCUMENT_HYBRID_NODE = "document_hybrid"
COLLECT_RETRIEVAL_OUTCOMES_NODE = "collect_retrieval_outcomes"


def build_rag_graph(
    *,
    model: BaseChatModel,
    document_retriever_factory: Any | None,
    retrieval_options: DocumentRetrievalOptions | None = None,
) -> StateGraph:
    """仅从实际注册的 Retriever 节点构建能力与动态路由。"""

    if document_retriever_factory is None:
        raise ValueError(
            "at least one retriever node must be registered"
        )
    options = retrieval_options or DocumentRetrievalOptions()
    retriever_destinations = {
        RetrieverKind.DOCUMENT_HYBRID: DOCUMENT_HYBRID_NODE
    }

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
            retriever_destinations=retriever_destinations,
        ),
        destinations=tuple(retriever_destinations.values()),
    )
    graph.add_node(
        DOCUMENT_HYBRID_NODE,
        partial(
            document_hybrid_node,
            retriever_factory=document_retriever_factory,
            options=options,
        ),
    )
    graph.add_node(
        COLLECT_RETRIEVAL_OUTCOMES_NODE,
        collect_retrieval_outcomes_node,
    )
    graph.add_edge(START, QUERY_REWRITE_NODE)
    graph.add_edge(QUERY_REWRITE_NODE, QUERY_ROUTER_NODE)
    graph.add_edge(
        DOCUMENT_HYBRID_NODE,
        COLLECT_RETRIEVAL_OUTCOMES_NODE,
    )
    graph.add_edge(COLLECT_RETRIEVAL_OUTCOMES_NODE, END)
    return graph
