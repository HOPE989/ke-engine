"""Chat API 启动期依赖装配与资源生命周期管理。

模型、业务数据库、PostgreSQL checkpointer 和 compiled Graph 都在 FastAPI lifespan
内创建，避免模块导入时连接外部资源。关闭时由统一的 LIFO stack 逆序清理。
"""

from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
import inspect
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from app.core.config import Settings, validate_chat_startup_settings
from app.domains.chat.graph import build_chat_graph
from app.domains.chat.services.title import TITLE_MODEL
from app.infrastructure.langgraph import postgres_checkpointer
from app.infrastructure.llm import create_chat_model
from app.infrastructure.redis import create_redis_client
from app.infrastructure.snowflake import SnowflakeIdGenerator
from app.services.document_api.deps import initialize_database_deps


class ChatResourceStack:
    """按 LIFO 管理 Chat API 启动期的同步与异步清理动作。

    它是 ``AsyncExitStack`` 的窄封装，使数据库、checkpointer 和 producer registry
    共用同一释放顺序，同时允许测试替换资源构造函数。
    """

    def __init__(self) -> None:
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "ChatResourceStack":
        await self._stack.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool | None:
        return await self._stack.__aexit__(exc_type, exc, tb)

    async def enter_async_context(self, context_manager: Any) -> Any:
        return await self._stack.enter_async_context(context_manager)

    def push_cleanup(self, callback: Callable[..., Any], *args: Any) -> None:
        """注册可同步或异步执行的清理回调。"""

        async def cleanup() -> None:
            result = callback(*args)
            if inspect.isawaitable(result):
                await result

        self._stack.push_async_callback(cleanup)


def create_producer_registry() -> Any:
    """延迟导入并创建 producer registry，避免装配模块形成循环依赖。"""

    from app.domains.chat.services.runtime import CompletionProducerRegistry

    return CompletionProducerRegistry()


@dataclass(frozen=True, slots=True)
class ChatApiDeps:
    """一次 Chat API lifespan 内共享的已就绪运行依赖。"""

    session_factory: Any
    id_generator: Any
    graph: Any
    model: Any
    title_model: Any
    redis_client: Any
    completion_lock_expire_seconds: int
    producer_registry: Any


def get_chat_deps(request: Request) -> ChatApiDeps:
    """从应用状态取得 Chat 依赖；尚未就绪时返回明确的 503。"""

    chat_deps = getattr(request.app.state, "chat_deps", None)
    if chat_deps is None:
        raise HTTPException(status_code=503, detail="Chat dependencies not available")
    return chat_deps


@asynccontextmanager
async def application_lifespan_resources(
    application: FastAPI,
    settings: Settings,
) -> AsyncGenerator[None, None]:
    """初始化、挂载并逆序释放 Chat API 的全部运行资源。

    启动配置或任一外部资源失败会中止应用启动，不回退到内存 checkpointer。yield
    之后的释放顺序与注册顺序相反：先移除应用依赖并等待 producer，再关闭 saver
    和业务数据库资源。
    """

    # 步骤 1：在建立外部连接前校验 Chat 专属配置，让启动错误尽早暴露。
    validate_chat_startup_settings(settings)
    async with ChatResourceStack() as stack:
        # 步骤 2：先准备业务数据库与模型，再建立独立的 checkpoint 连接池。
        session_factory = await initialize_database_deps(stack=stack, settings=settings)
        model = create_chat_model(settings, model=settings.openai_model)
        title_model = create_chat_model(settings, model=TITLE_MODEL)
        saver = await stack.enter_async_context(postgres_checkpointer(settings.database_url))

        # 步骤 3：Redis client 与 saver 都必须在 Registry 关闭后再释放，确保仍在后台
        # 执行的 completion 可以在最终退出路径释放分布式锁。
        redis_client = create_redis_client(settings.redis_url)
        stack.push_cleanup(redis_client.close)

        # 步骤 4：只有 saver 完成 setup 后才编译生产 Graph，确保首次请求即可持久化 state。
        graph = build_chat_graph().compile(checkpointer=saver)
        producer_registry = create_producer_registry()
        stack.push_cleanup(producer_registry.shutdown)

        # 步骤 5：所有依赖就绪后一次性挂载；LIFO 清理会先移除状态并等待 producer。
        application.state.chat_deps = ChatApiDeps(
            session_factory=session_factory,
            id_generator=SnowflakeIdGenerator(worker_id=settings.snowflake_worker_id),
            graph=graph,
            model=model,
            title_model=title_model,
            redis_client=redis_client,
            completion_lock_expire_seconds=settings.chat_completion_lock_expire_seconds,
            producer_registry=producer_registry,
        )
        stack.push_cleanup(_discard_app_state_attr, application, "chat_deps")
        yield


def _discard_app_state_attr(application: FastAPI, attr: str) -> None:
    """移除 lifespan 挂载的状态，防止关闭中的请求继续取得已释放资源。"""

    if hasattr(application.state, attr):
        delattr(application.state, attr)
