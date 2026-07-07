"""Kafka worker process entrypoint."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
import inspect
from typing import Any

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.modules.document.workers.conversion import run_document_conversion_consumer
from app.modules.document.workers.vector_storage import run_document_vector_storage_consumer


class RuntimeResourceStack:
    """Kafka worker 进程 runtime 构造阶段使用的资源清理栈。

    1. worker 启动期创建 DB、Redis、MinerU、模型、ES 等长生命周期资源；
    2. 每个资源必须显式登记 close/aclose/dispose 回调；
    3. worker 退出时按创建相反顺序释放，避免业务 handler 关闭 runtime-owned 资源。
    """

    def __init__(self) -> None:
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "RuntimeResourceStack":
        await self._stack.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool | None:
        return await self._stack.__aexit__(exc_type, exc, tb)

    def push_cleanup(self, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """登记 Kafka worker 进程级资源清理回调。"""

        async def cleanup() -> None:
            result = callback(*args, **kwargs)
            if inspect.isawaitable(result):
                await result

        self._stack.push_async_callback(cleanup)


class RuntimeImageDescriber:
    """Kafka worker 持有的图片描述模型适配器。

    PDF 转换时只调用这个适配器；底层 chat model 在 Kafka worker 启动期构造，避免每条
    conversion message 重复初始化外部模型客户端。
    """

    def __init__(self, *, model: Any) -> None:
        self._model = model

    async def describe_image(self, *, filename: str, content: bytes, content_type: str) -> str:
        """调用启动期创建的图片理解模型，返回一条中文图片描述。"""

        import base64

        from langchain_core.messages import HumanMessage

        encoded = base64.b64encode(content).decode("ascii")
        response = await self._model.ainvoke(
            [
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": f"请用一句简洁中文描述图片 {filename} 的主要内容。",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{content_type};base64,{encoded}",
                            },
                        },
                    ],
                )
            ]
        )
        return str(response.content)


def create_runtime_image_describer(settings: Any) -> RuntimeImageDescriber:
    """按 Kafka worker 启动期配置创建图片描述模型。"""

    from langchain_openai import ChatOpenAI

    api_key = _clean_value(getattr(settings, "openai_api_key", None))
    if api_key is None:
        raise RuntimeError("OPENAI_API_KEY is required for document image description")

    kwargs: dict[str, str] = {
        "api_key": api_key,
        "model": "qwen3.6-flash",
    }
    base_url = _clean_value(getattr(settings, "openai_base_url", None))
    if base_url is not None:
        kwargs["base_url"] = base_url
    return RuntimeImageDescriber(model=ChatOpenAI(**kwargs))


async def initialize_runtime_database(*, stack: RuntimeResourceStack, settings: Any) -> Any:
    """初始化 Kafka worker 进程拥有的 DB engine 与 session factory。"""

    from app.db import session as db_session

    await db_session.init_engine(settings.database_url)
    stack.push_cleanup(db_session.close_engine)
    return db_session.get_session_factory()


@dataclass(frozen=True, slots=True)
class DocumentConversionContext:
    """Kafka 文档转换 consumer 使用的资源视图。

    该 context 不拥有生命周期，只暴露 `KafkaWorkerRuntime` 启动期创建的转换链路资源。
    """

    repository: Any
    redis_client: Any
    storage: Any
    mineru_client: Any
    image_describer: Any
    converter_factory: Any
    lock_expire_seconds: int


@dataclass(frozen=True, slots=True)
class DocumentVectorStorageContext:
    """Kafka 向量写入 consumer 使用的资源视图。"""

    repository: Any
    redis_client: Any
    embedding_model: Any
    vector_store: Any
    lock_expire_seconds: int


@dataclass(frozen=True, slots=True)
class KafkaWorkerRuntime:
    """Kafka worker 进程启动期拥有的长生命周期资源集合。

    conversion/vector-storage context 只是资源视图；真正的创建和释放责任属于这个 worker
    host 里的 `RuntimeResourceStack`。
    """

    settings: Any
    session_factory: Any
    conversion: DocumentConversionContext
    vector_storage: DocumentVectorStorageContext


async def create_kafka_worker_runtime(
    *,
    stack: RuntimeResourceStack,
    settings: Any,
) -> KafkaWorkerRuntime:
    """创建 Kafka worker 进程共享的 `KafkaWorkerRuntime`。

    1. 启动期一次性初始化长生命周期基础设施；
    2. conversion 与 vector-storage consumer 共享同一个进程 runtime；
    3. Kafka consumer 实例仍在各自 runner 内独立创建，保持 topic/group/offset 状态隔离。
    """

    session_factory = await initialize_runtime_database(stack=stack, settings=settings)
    repository = _create_worker_repository(session_factory)
    redis_client = _create_worker_redis_client(stack=stack, settings=settings)

    # 1. 转换 context 暴露 DB/Redis/MinIO/MinerU/图片模型/factory 资源视图。
    storage = await _maybe_await(_create_worker_document_storage(settings=settings))
    mineru_client = _create_worker_mineru_client(stack=stack, settings=settings)
    image_describer = _create_worker_image_describer(stack=stack, settings=settings)
    converter_factory = _create_document_converter_factory()
    conversion = DocumentConversionContext(
        repository=repository,
        redis_client=redis_client,
        storage=storage,
        mineru_client=mineru_client,
        image_describer=image_describer,
        converter_factory=converter_factory,
        lock_expire_seconds=settings.document_convert_lock_expire_seconds,
    )

    # 2. 向量 context 暴露 DB/Redis/embedding/ES adapter 资源视图。
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

    return KafkaWorkerRuntime(
        settings=settings,
        session_factory=session_factory,
        conversion=conversion,
        vector_storage=vector_storage,
    )


def _create_worker_repository(session_factory: Any) -> Any:
    from app.modules.document.repository import DocumentRepository

    return DocumentRepository(session_factory)


def _create_worker_redis_client(*, stack: RuntimeResourceStack, settings: Any) -> Any:
    from app.infrastructure.redis_lock import create_redis_client

    redis_client = create_redis_client(settings.redis_url)
    stack.push_cleanup(redis_client.close)
    return redis_client


async def _create_worker_document_storage(*, settings: Any) -> Any:
    from app.infrastructure.minio import ensure_minio_bucket, get_minio_client
    from app.modules.document.storage import DocumentObjectStorage

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


def _create_document_converter_factory() -> Any:
    """在 Kafka worker 启动期创建文档转换器工厂。"""

    from app.modules.document.converters import create_default_document_converter_factory

    return create_default_document_converter_factory()


def _create_worker_embedding_model(*, settings: Any) -> Any:
    from app.modules.document.vector_store import create_embedding_model

    return create_embedding_model(settings)


def _create_worker_vector_store(
    *,
    stack: RuntimeResourceStack,
    settings: Any,
    embedding_model: Any,
) -> Any:
    from app.modules.document.vector_store import (
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


def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


async def start_worker_consumers() -> None:
    """启动 Kafka worker 的所有模块 consumer。

    1. 先创建一个 worker 进程级 `KafkaWorkerRuntime`；
    2. conversion 与 vector-storage consumer 共享基础设施 runtime；
    3. 每个 consumer runner 内部仍独立创建自己的 Kafka consumer 实例。
    """

    settings = get_settings()
    async with RuntimeResourceStack() as stack:
        runtime = await create_kafka_worker_runtime(
            stack=stack,
            settings=settings,
        )
        async with asyncio.TaskGroup() as task_group:
            task_group.create_task(run_document_conversion_consumer(runtime))
            task_group.create_task(run_document_vector_storage_consumer(runtime))


async def main() -> None:
    configure_logging()
    await start_worker_consumers()


if __name__ == "__main__":
    asyncio.run(main())
