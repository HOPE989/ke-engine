"""供本地 LangGraph Agent Server/Studio 加载的 RAG Graph。"""

from langchain_core.runnables import RunnableConfig

from app.core.config import create_settings, validate_chat_startup_settings
from app.infrastructure.rag_runtime import create_compiled_rag_graph


def create_rag_studio_graph(
    config: RunnableConfig | None = None,
):
    """绑定开发模型并编译当前 RAG 管线，不启动应用服务资源。"""

    del config
    settings = validate_chat_startup_settings(create_settings())
    return create_compiled_rag_graph(settings)
