"""供本地 LangGraph Agent Server/Studio 加载的 RAG Graph。"""

from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import create_settings, validate_chat_startup_settings
from app.domains.document.repositories.segment_repository import (
    SegmentRepository,
)
from app.domains.rag.graph import build_rag_graph
from app.domains.rag.graph.retrieval import DocumentRetrievalOptions
from app.infrastructure.elasticsearch import (
    DocumentHybridRetrieverFactory,
    create_document_retrieval_store,
    create_elasticsearch_client,
)
from app.infrastructure.langfuse import create_langfuse_resources
from app.infrastructure.llm import (
    create_chat_model,
    create_embedding_model,
)
from app.infrastructure.parent_chunks import CachedParentChunkLoader
from app.infrastructure.redis import create_redis_client
from app.infrastructure.rerank import (
    BailianQwen3Reranker,
    get_shared_rerank_http_client,
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
    options = DocumentRetrievalOptions()
    reranker = BailianQwen3Reranker(
        http_client=get_shared_rerank_http_client(),
        openai_base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        timeout_seconds=options.timeout_seconds,
    )
    store = create_document_retrieval_store(
        settings=settings,
        embedding_model=embedding_model,
        client=client,
    )
    parent_chunk_cache = create_parent_chunk_cache(settings)
    retriever_factory = DocumentHybridRetrieverFactory(
        client=client,
        store=store,
        index_name=settings.elasticsearch_index,
        options=options,
        reranker=reranker,
        parent_chunk_cache=parent_chunk_cache,
    )
    return build_rag_graph(
        model=model,
        document_retriever_factory=retriever_factory,
        retrieval_options=options,
    ).compile()


def create_parent_chunk_cache(settings):
    """为 Studio 创建带 Redis 缓存的父分段批量读取器。"""

    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"ssl": False},
    )
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    return CachedParentChunkLoader(
        repository=SegmentRepository(session_factory),
        redis_client=create_redis_client(settings.redis_url),
    )
