"""声明首版生产 Chat Graph 的最小拓扑。"""

from langgraph.graph import END, START, StateGraph

from app.domains.chat.graph.context import ChatRuntimeContext
from app.domains.chat.graph.nodes.llm import llm_node
from app.domains.chat.graph.state import ChatState

LLM_NODE = "llm"


def build_chat_graph() -> StateGraph:
    """声明 ``START -> llm -> END``，但不在领域层编译 Graph。

    编译需要生命周期内就绪的 PostgreSQL saver，因此由 Chat API 装配层完成。builder
    不创建模型、不读取 settings，也不为 LLM 节点配置自动重试。
    """

    # 领域层只描述稳定拓扑；运行资源通过 context schema 和 compile 参数注入。
    graph = StateGraph(ChatState, context_schema=ChatRuntimeContext)
    graph.add_node(LLM_NODE, llm_node)
    graph.add_edge(START, LLM_NODE)
    graph.add_edge(LLM_NODE, END)
    return graph
