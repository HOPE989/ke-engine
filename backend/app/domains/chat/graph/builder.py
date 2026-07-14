"""最小 Chat Graph builder。"""

from langgraph.graph import END, START, StateGraph

from app.domains.chat.graph.context import ChatRuntimeContext
from app.domains.chat.graph.nodes.llm import llm_node
from app.domains.chat.graph.state import ChatState

LLM_NODE = "llm"


def build_chat_graph() -> StateGraph:
    """声明但不编译生产 Chat Graph。"""

    graph = StateGraph(ChatState, context_schema=ChatRuntimeContext)
    graph.add_node(LLM_NODE, llm_node)
    graph.add_edge(START, LLM_NODE)
    graph.add_edge(LLM_NODE, END)
    return graph
