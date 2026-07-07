"""API 层运行时初始化与请求期配置访问器。"""

from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
import inspect
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from app.core.config import Settings


class RuntimeResourceStack:
    """API 进程 runtime 构造阶段使用的长生命周期资源清理栈。

    1. API lifespan 创建资源时登记显式 cleanup 回调；
    2. 退出 lifespan 时按后进先出顺序释放资源；
    3. 同步 close 与返回 awaitable 的异步 close 都在这里统一处理。
    """

    def __init__(self) -> None:
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "RuntimeResourceStack":
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


async def initialize_runtime_database(*, stack: RuntimeResourceStack, settings: Any) -> Any:
    """初始化 API 进程拥有的 DB engine 与 session factory。

    1. lifespan 启动时创建全进程共享的 async engine；
    2. HTTP 请求只复用 `session_factory` 创建短生命周期 session；
    3. engine 关闭回调登记在 API runtime cleanup 栈中。
    """

    from app.db import session as db_session

    await db_session.init_engine(settings.database_url)
    stack.push_cleanup(db_session.close_engine)
    return db_session.get_session_factory()


@dataclass(frozen=True, slots=True)
class DocumentRuntime:
    """document 模块在 API 进程内使用的长生命周期资源集合。

    1. 该对象只暴露 document HTTP 路由实际需要的资源；
    2. 底层 DB/Redis/MinIO/Kafka 等对象仍由 FastAPI lifespan 统一创建和释放；
    3. 后续新增 chat 等模块时，应新增独立的 `application.state.<module>_runtime`。
    """

    repository: Any
    storage: Any
    file_detector: Any
    id_generator: Any
    conversion_dispatcher: Any
    embed_store_dispatcher: Any
    splitter_factory: Any
    redis_client: Any


def get_config(request: Request) -> Settings:
    """返回 API 进程启动期捕获的配置快照。

    请求处理只读取 `application.state.settings`，不重新构造完整配置对象；需要变更基础设施配置时，
    通过重启 API 进程让新的 startup settings 生效。
    """

    try:
        return request.app.state.settings
    except AttributeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Application settings not available",
        ) from exc


def get_document_runtime(request: Request) -> DocumentRuntime:
    """返回 document 模块装配的 API 运行时资源，缺失时返回 503。"""

    document_runtime = getattr(request.app.state, "document_runtime", None)
    if document_runtime is None:
        raise HTTPException(
            status_code=503,
            detail="Document runtime not available",
        )
    return document_runtime


@asynccontextmanager
async def application_lifespan_resources(
    application: FastAPI,
    settings: Settings,
) -> AsyncGenerator[None, None]:
    """初始化并释放 API 进程启动期资源。

    1. DB/Redis/MinIO/Kafka 等基础设施在同一个 lifespan 中统一初始化；
    2. 启动期配置快照挂到 `state.settings`，避免请求期重新构造完整 settings；
    3. 当前只有 document 模块，因此只装配 `state.document_runtime`；
    4. 后续新增模块时，在这里继续装配各自的 `state.<module>_runtime`。
    """

    from app.infrastructure.kafka import create_kafka_producer
    from app.infrastructure.magika import get_magika_client
    from app.infrastructure.minio import ensure_minio_bucket, get_minio_client
    from app.infrastructure.redis_lock import create_redis_client
    from app.infrastructure.snowflake import SnowflakeIdGenerator
    from app.modules.document.dispatcher import (
        KafkaDocumentConversionDispatcher,
        KafkaDocumentEmbedStoreDispatcher,
    )
    from app.modules.document.chunking import create_default_document_splitter_factory
    from app.modules.document.repository import DocumentRepository
    from app.modules.document.storage import DocumentObjectStorage

    async with RuntimeResourceStack() as stack:
        # 1. DB engine/session factory 属于 API 进程 runtime，不属于单个 HTTP 请求。
        session_factory = await initialize_runtime_database(stack=stack, settings=settings)

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

        # 2. document 模块 runtime 只包含该模块路由会读取的资源。
        document_runtime = DocumentRuntime(
            repository=DocumentRepository(session_factory),
            storage=storage,
            file_detector=get_magika_client(),
            id_generator=SnowflakeIdGenerator(worker_id=settings.snowflake_worker_id),
            conversion_dispatcher=KafkaDocumentConversionDispatcher(kafka_producer),
            embed_store_dispatcher=KafkaDocumentEmbedStoreDispatcher(kafka_producer),
            splitter_factory=create_default_document_splitter_factory(),
            redis_client=redis_client,
        )

        # 3. app.state 只暴露启动期 settings 与模块级 runtime，不再引入 API 总 runtime。
        application.state.settings = settings
        application.state.document_runtime = document_runtime
        stack.push_cleanup(_discard_app_state_attr, application, "settings")
        stack.push_cleanup(_discard_app_state_attr, application, "document_runtime")

        yield


def _discard_app_state_attr(application: FastAPI, attr: str) -> None:
    """删除 app.state 上的临时属性，缺失时忽略。"""

    if hasattr(application.state, attr):
        delattr(application.state, attr)

