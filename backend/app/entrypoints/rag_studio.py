"""供本地 LangGraph Agent Server/Studio 加载的 RAG Graph。"""

from langchain_core.runnables import RunnableConfig

from app.core.config import create_settings, validate_chat_startup_settings
from app.domains.rag.graph import build_rag_graph
from app.infrastructure.langfuse import create_langfuse_resources
from app.infrastructure.llm import create_chat_model


def create_rag_studio_graph(
    config: RunnableConfig | None = None,
):
    """绑定开发模型并编译当前 RAG 管线，不启动应用服务资源。"""

    del config
    settings = validate_chat_startup_settings(create_settings())
    langfuse = create_langfuse_resources(settings)
    callbacks = [langfuse.handler] if langfuse is not None else None
    model = create_chat_model(
        settings,
        model=settings.openai_model,
        callbacks=callbacks,
    )
    return build_rag_graph(bound_model=model).compile()
