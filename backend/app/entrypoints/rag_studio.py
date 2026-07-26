"""供本地 LangGraph Agent Server/Studio 加载的 RAG Graph。"""

from langchain_core.runnables import RunnableConfig

from app.core.config import create_settings, validate_chat_startup_settings
from app.domains.rag.graph import build_rag_graph
from app.domains.rag.graph.retrieval import DocumentRetrievalOptions
from app.infrastructure.elasticsearch import (
    DocumentHybridRetrieverFactory,
    create_document_retrieval_store,
    create_elasticsearch_client,
    ensure_vector_index,
)
from app.infrastructure.langfuse import create_langfuse_resources
from app.infrastructure.llm import (
    create_chat_model,
    create_embedding_model,
)


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
    embedding_model = create_embedding_model(settings)
    client = create_elasticsearch_client(settings)
    ensure_vector_index(
        client,
        index_name=settings.elasticsearch_index,
        embedding_dimensions=settings.embedding_dimensions,
    )
    options = DocumentRetrievalOptions()
    store = create_document_retrieval_store(
        settings=settings,
        embedding_model=embedding_model,
        client=client,
    )
    retriever_factory = DocumentHybridRetrieverFactory(
        client=client,
        store=store,
        index_name=settings.elasticsearch_index,
        options=options,
    )
    return build_rag_graph(
        model=model,
        document_retriever_factory=retriever_factory,
        retrieval_options=options,
    ).compile()
