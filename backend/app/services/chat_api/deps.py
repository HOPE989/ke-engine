"""Chat API 生命周期依赖装配。"""

from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
import inspect
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from app.core.config import Settings, validate_chat_startup_settings
from app.domains.chat.graph import build_chat_graph
from app.infrastructure.langgraph import postgres_checkpointer
from app.infrastructure.llm import create_chat_model
from app.infrastructure.snowflake import SnowflakeIdGenerator
from app.services.document_api.deps import initialize_database_deps


class ChatResourceStack:
    """按 LIFO 管理 Chat API 启动期资源。"""

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
        async def cleanup() -> None:
            result = callback(*args)
            if inspect.isawaitable(result):
                await result

        self._stack.push_async_callback(cleanup)


class LifespanProducerRegistry:
    """为后续 producer task registry 保留的生命周期边界。"""

    async def shutdown(self) -> None:
        return None


def create_producer_registry() -> LifespanProducerRegistry:
    return LifespanProducerRegistry()


@dataclass(frozen=True, slots=True)
class ChatApiDeps:
    session_factory: Any
    id_generator: Any
    graph: Any
    model: Any
    producer_registry: Any


def get_chat_deps(request: Request) -> ChatApiDeps:
    chat_deps = getattr(request.app.state, "chat_deps", None)
    if chat_deps is None:
        raise HTTPException(status_code=503, detail="Chat dependencies not available")
    return chat_deps


@asynccontextmanager
async def application_lifespan_resources(
    application: FastAPI,
    settings: Settings,
) -> AsyncGenerator[None, None]:
    """初始化并逆序释放 Chat API 资源。"""

    validate_chat_startup_settings(settings)
    async with ChatResourceStack() as stack:
        session_factory = await initialize_database_deps(stack=stack, settings=settings)
        model = create_chat_model(settings, model=settings.openai_model)
        saver = await stack.enter_async_context(postgres_checkpointer(settings.database_url))
        graph = build_chat_graph().compile(checkpointer=saver)
        producer_registry = create_producer_registry()
        stack.push_cleanup(producer_registry.shutdown)

        application.state.chat_deps = ChatApiDeps(
            session_factory=session_factory,
            id_generator=SnowflakeIdGenerator(worker_id=settings.snowflake_worker_id),
            graph=graph,
            model=model,
            producer_registry=producer_registry,
        )
        stack.push_cleanup(_discard_app_state_attr, application, "chat_deps")
        yield


def _discard_app_state_attr(application: FastAPI, attr: str) -> None:
    if hasattr(application.state, attr):
        delattr(application.state, attr)
