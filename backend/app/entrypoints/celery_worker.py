"""Celery worker process entrypoint."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
import inspect
import threading
from typing import Any

from celery.signals import worker_process_init, worker_process_shutdown

from app.core.config import get_settings
from app.domains.document.components.image_describer import RuntimeImageDescriber
from app.infrastructure.celery_app import create_celery_app
from app.infrastructure.llm import create_chat_model


class RuntimeResourceStack:
    """Celery worker 子进程 runtime 构造阶段使用的资源清理栈。

    1. 每个 Celery 子进程单独创建自己的 DB、Redis、模型和 ES 资源；
    2. cleanup 必须在创建这些 async client 的长期 loop 上执行；
    3. 单次 Celery task 只提交工作，不负责关闭进程级资源。
    """

    def __init__(self) -> None:
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "RuntimeResourceStack":
        await self._stack.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool | None:
        return await self._stack.__aexit__(exc_type, exc, tb)

    def push_cleanup(self, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """登记 Celery 子进程级资源清理回调。"""

        async def cleanup() -> None:
            result = callback(*args, **kwargs)
            if inspect.isawaitable(result):
                await result

        self._stack.push_async_callback(cleanup)


def create_runtime_image_describer(settings: Any) -> RuntimeImageDescriber:
    """按 Celery 子进程启动期配置创建图片描述模型。"""

    return RuntimeImageDescriber(model=create_chat_model(settings, model="qwen3.6-flash"))


async def initialize_runtime_database(*, stack: RuntimeResourceStack, settings: Any) -> Any:
    """初始化 Celery 子进程拥有的 DB engine 与 session factory。"""

    from app.infrastructure.db import session as db_session

    await db_session.init_engine(settings.database_url)
    stack.push_cleanup(db_session.close_engine)
    return db_session.get_session_factory()


@dataclass(frozen=True, slots=True)
class DocumentVectorStorageContext:
    """Celery 补偿复用的向量写入资源视图。"""

    repository: Any
    redis_client: Any
    embedding_model: Any
    vector_store: Any
    lock_expire_seconds: int


@dataclass(frozen=True, slots=True)
class DocumentCompensationContext:
    """Celery 补偿 task 使用的资源视图。"""

    repository: Any
    storage: Any
    mineru_client: Any
    image_describer: Any
    vector_storage: DocumentVectorStorageContext


@dataclass(frozen=True, slots=True)
class CeleryWorkerRuntime:
    """Celery worker 子进程启动期拥有的长生命周期资源集合。"""

    settings: Any
    session_factory: Any
    compensation: DocumentCompensationContext


async def create_celery_worker_runtime(
    *,
    stack: RuntimeResourceStack,
    settings: Any,
) -> CeleryWorkerRuntime:
    """创建 Celery 子进程共享的 `CeleryWorkerRuntime`。

    1. 该函数只在 worker_process_init 阶段的长期 loop 上调用；
    2. compensation context 暴露补偿流程需要的资源视图；
    3. 资源释放由 worker_process_shutdown 阶段执行 cleanup 栈完成。
    """

    session_factory = await initialize_runtime_database(stack=stack, settings=settings)
    repository = _create_worker_repository(session_factory)
    redis_client = _create_worker_redis_client(stack=stack, settings=settings)
    storage = await _maybe_await(_create_worker_document_storage(settings=settings))
    mineru_client = _create_worker_mineru_client(stack=stack, settings=settings)
    image_describer = _create_worker_image_describer(stack=stack, settings=settings)
    embedding_model = _create_worker_embedding_model(settings=settings)
    vector_store = _create_worker_vector_store(
        stack=stack,
        settings=settings,
        embedding_model=embedding_model,
    )

    vector_storage = DocumentVectorStorageContext(
        repository=repository,
        redis_client=redis_client,
        embedding_model=embedding_model,
        vector_store=vector_store,
        lock_expire_seconds=settings.document_convert_lock_expire_seconds,
    )
    compensation = DocumentCompensationContext(
        repository=repository,
        storage=storage,
        mineru_client=mineru_client,
        image_describer=image_describer,
        vector_storage=vector_storage,
    )
    return CeleryWorkerRuntime(
        settings=settings,
        session_factory=session_factory,
        compensation=compensation,
    )


def _create_worker_repository(session_factory: Any) -> Any:
    from app.domains.document.repositories.document_repository import DocumentRepository

    return DocumentRepository(session_factory)


def _create_worker_redis_client(*, stack: RuntimeResourceStack, settings: Any) -> Any:
    from app.infrastructure.redis import create_redis_client

    redis_client = create_redis_client(settings.redis_url)
    stack.push_cleanup(redis_client.close)
    return redis_client


async def _create_worker_document_storage(*, settings: Any) -> Any:
    from app.infrastructure.minio import ensure_minio_bucket, get_minio_client
    from app.domains.document.components.storage import DocumentObjectStorage

    minio_client = get_minio_client()
    await ensure_minio_bucket(minio_client, settings.minio_bucket)
    return DocumentObjectStorage(
        client=minio_client,
        bucket=settings.minio_bucket,
        public_base_url=settings.minio_public_base_url,
    )


def _create_worker_mineru_client(*, stack: RuntimeResourceStack, settings: Any) -> Any:
    from app.infrastructure.mineru import create_mineru_client

    mineru_client = create_mineru_client(settings)
    _push_named_cleanup(stack, mineru_client, "aclose")
    return mineru_client


def _create_worker_image_describer(*, stack: RuntimeResourceStack, settings: Any) -> Any:
    image_describer = create_runtime_image_describer(settings)
    _push_named_cleanup(stack, image_describer, "aclose")
    _push_named_cleanup(stack, image_describer, "close")
    return image_describer


def _create_worker_embedding_model(*, settings: Any) -> Any:
    from app.infrastructure.llm import create_embedding_model

    return create_embedding_model(settings)


def _create_worker_vector_store(
    *,
    stack: RuntimeResourceStack,
    settings: Any,
    embedding_model: Any,
) -> Any:
    from app.infrastructure.elasticsearch import (
        ElasticsearchVectorStoreAdapter,
        create_elasticsearch_store,
    )

    es_store = create_elasticsearch_store(settings=settings, embedding_model=embedding_model)
    es_client = getattr(es_store, "client", None)
    if es_client is not None:
        _push_named_cleanup(stack, es_client, "close")
        _push_named_cleanup(stack, es_client, "aclose")
    return ElasticsearchVectorStoreAdapter(
        store=es_store,
        client=es_client,
        index_name=settings.elasticsearch_index,
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _push_named_cleanup(stack: RuntimeResourceStack, resource: Any, name: str) -> None:
    callback = getattr(resource, name, None)
    if callback is not None:
        stack.push_cleanup(callback)


_celery_worker_runtime: CeleryWorkerRuntime | None = None
_celery_worker_loop: asyncio.AbstractEventLoop | None = None
_celery_worker_loop_thread: threading.Thread | None = None
_celery_worker_runtime_stack: RuntimeResourceStack | None = None


def set_celery_worker_runtime(runtime: CeleryWorkerRuntime | None) -> None:
    """登记当前 Celery 子进程拥有的进程级 runtime。

    该状态属于 worker host，而不是某个 document task。业务 task 只读取这里暴露的 runtime，
    不负责创建或销毁 Redis、DB、MinIO、MinerU、模型和向量存储等长生命周期资源。
    """

    global _celery_worker_runtime
    _celery_worker_runtime = runtime


def get_celery_worker_runtime() -> CeleryWorkerRuntime:
    """返回当前 Celery 子进程 runtime，未初始化时抛出明确错误。"""

    if _celery_worker_runtime is None:
        raise RuntimeError("Celery worker runtime has not been initialized")
    return _celery_worker_runtime


def start_celery_worker_runtime() -> None:
    """在 Celery worker 子进程中创建长期 asyncio loop 并初始化 runtime。

    1. 子进程启动后创建一个专属 event loop；
    2. loop 运行在线程中，供同步 Celery task 提交 async 工作；
    3. `CeleryWorkerRuntime` 在该 loop 上初始化，保证 async client 创建和使用在同一 loop。
    """

    global _celery_worker_loop, _celery_worker_loop_thread
    if _celery_worker_loop is not None:
        return

    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run_loop() -> None:
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()

    thread = threading.Thread(
        target=run_loop,
        name="celery-document-runtime-loop",
        daemon=True,
    )
    thread.start()
    ready.wait()

    _celery_worker_loop = loop
    _celery_worker_loop_thread = thread
    asyncio.run_coroutine_threadsafe(_initialize_celery_worker_runtime(), loop).result()


async def _initialize_celery_worker_runtime() -> None:
    """在 Celery 子进程长期 loop 上构造 runtime 并保存 cleanup 栈。"""

    global _celery_worker_runtime_stack
    stack = RuntimeResourceStack()
    await stack.__aenter__()
    try:
        runtime = await create_celery_worker_runtime(
            stack=stack,
            settings=get_settings(),
        )
    except Exception:
        await stack.__aexit__(None, None, None)
        raise

    _celery_worker_runtime_stack = stack
    set_celery_worker_runtime(runtime)


def shutdown_celery_worker_runtime() -> None:
    """释放 Celery 子进程 runtime 资源并关闭长期 event loop。

    1. cleanup 栈必须在创建 runtime 的同一个 loop 上执行；
    2. runtime 资源释放完成后再停止 loop，等待 loop 线程退出；
    3. 最后关闭 loop 并清空模块级引用，避免子进程复用到已关闭资源。
    """

    global _celery_worker_loop, _celery_worker_loop_thread, _celery_worker_runtime_stack
    loop = _celery_worker_loop
    thread = _celery_worker_loop_thread
    stack = _celery_worker_runtime_stack
    set_celery_worker_runtime(None)
    _celery_worker_runtime_stack = None

    if loop is not None and stack is not None:
        asyncio.run_coroutine_threadsafe(
            _close_celery_worker_runtime_stack(stack),
            loop,
        ).result()

    if loop is not None:
        loop.call_soon_threadsafe(loop.stop)
    if thread is not None:
        thread.join(timeout=5)
    if loop is not None and not loop.is_closed():
        loop.close()

    _celery_worker_loop = None
    _celery_worker_loop_thread = None


async def _close_celery_worker_runtime_stack(stack: RuntimeResourceStack) -> None:
    """在 runtime 所属 event loop 上执行 cleanup 栈退出逻辑。"""

    await stack.__aexit__(None, None, None)


def submit_celery_runtime_coroutine(coroutine):
    """把 Celery task 产生的 coroutine 提交到子进程长期 loop 并等待结果。

    同步 Celery task 不能直接 `await`，也不能每次 `asyncio.run()` 创建新 loop；这里统一通过
    worker_process_init 阶段创建的 loop 执行异步补偿流程。
    """

    if _celery_worker_loop is None:
        coroutine.close()
        raise RuntimeError("Celery worker event loop has not been initialized")
    return asyncio.run_coroutine_threadsafe(coroutine, _celery_worker_loop).result()


@worker_process_init.connect
def _on_worker_process_init(**_: object) -> None:
    """Celery 子进程启动信号：创建长期 loop 并初始化 runtime。"""

    start_celery_worker_runtime()


@worker_process_shutdown.connect
def _on_worker_process_shutdown(**_: object) -> None:
    """Celery 子进程关闭信号：释放 runtime 资源。"""

    shutdown_celery_worker_runtime()


celery_app = create_celery_app(
    include=[
        "app.domains.document.tasks.vector_storage_compensation",
    ]
)
