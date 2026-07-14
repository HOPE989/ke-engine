"""Document API 依赖装配与请求期访问器。"""

from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
import inspect
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from app.core.config import Settings


class ResourceCleanupStack:
    """API 进程资源构造阶段使用的长生命周期清理栈。"""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "ResourceCleanupStack":
        await self._stack.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool | None:
        return await self._stack.__aexit__(exc_type, exc, tb)

    def push_cleanup(self, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """登记一个 API 进程级资源清理回调。"""

        async def cleanup() -> None:
            result = callback(*args, **kwargs)
            if inspect.isawaitable(result):
                await result

        self._stack.push_async_callback(cleanup)


async def initialize_database_deps(*, stack: ResourceCleanupStack, settings: Any) -> Any:
    """初始化 API 进程拥有的 DB engine 与 session factory。"""

    from app.infrastructure.db import session as db_session

    await db_session.init_engine(settings.database_url)
    stack.push_cleanup(db_session.close_engine)
    return db_session.get_session_factory()


@dataclass(frozen=True, slots=True)
class DocumentApiDeps:
    """Document HTTP 路由需要的长生命周期依赖集合。"""

    repository: Any
    storage: Any
    file_detector: Any
    id_generator: Any
    conversion_dispatcher: Any
    embed_store_dispatcher: Any
    splitter_factory: Any
    redis_client: Any


def get_config(request: Request) -> Settings:
    """返回 Document API 启动期捕获的配置快照。"""

    try:
        return request.app.state.settings
    except AttributeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Application settings not available",
        ) from exc


def get_document_deps(request: Request) -> DocumentApiDeps:
    """返回 Document API 路由依赖集合，缺失时返回 503。"""

    document_deps = getattr(request.app.state, "document_deps", None)
    if document_deps is None:
        raise HTTPException(
            status_code=503,
            detail="Document dependencies not available",
        )
    return document_deps


@asynccontextmanager
async def application_lifespan_resources(
    application: FastAPI,
    settings: Settings,
) -> AsyncGenerator[None, None]:
    """初始化并释放 Document API 进程启动期资源。"""

    from app.domains.document.components.dispatcher import (
        KafkaDocumentConversionDispatcher,
        KafkaDocumentEmbedStoreDispatcher,
    )
    from app.domains.document.components.splitters import create_default_document_splitter_factory
    from app.domains.document.components.storage import DocumentObjectStorage
    from app.domains.document.repositories.document_repository import DocumentRepository
    from app.infrastructure.kafka import create_kafka_producer
    from app.infrastructure.magika import get_magika_client
    from app.infrastructure.minio import ensure_minio_bucket, get_minio_client
    from app.infrastructure.redis import create_redis_client
    from app.infrastructure.snowflake import SnowflakeIdGenerator

    async with ResourceCleanupStack() as stack:
        session_factory = await initialize_database_deps(stack=stack, settings=settings)

        minio_client = get_minio_client()
        await ensure_minio_bucket(minio_client, settings.minio_bucket)
        redis_client = create_redis_client(settings.redis_url)
        stack.push_cleanup(redis_client.close)

        storage = DocumentObjectStorage(
            client=minio_client,
            bucket=settings.minio_bucket,
            public_base_url=settings.minio_public_base_url,
        )

        kafka_producer = create_kafka_producer(settings.kafka_bootstrap_servers)
        document_deps = DocumentApiDeps(
            repository=DocumentRepository(session_factory),
            storage=storage,
            file_detector=get_magika_client(),
            id_generator=SnowflakeIdGenerator(worker_id=settings.snowflake_worker_id),
            conversion_dispatcher=KafkaDocumentConversionDispatcher(kafka_producer),
            embed_store_dispatcher=KafkaDocumentEmbedStoreDispatcher(kafka_producer),
            splitter_factory=create_default_document_splitter_factory(),
            redis_client=redis_client,
        )

        application.state.settings = settings
        application.state.document_deps = document_deps
        stack.push_cleanup(_discard_app_state_attr, application, "settings")
        stack.push_cleanup(_discard_app_state_attr, application, "document_deps")

        yield


def _discard_app_state_attr(application: FastAPI, attr: str) -> None:
    """删除 app.state 上的临时属性，缺失时忽略。"""

    if hasattr(application.state, attr):
        delattr(application.state, attr)
