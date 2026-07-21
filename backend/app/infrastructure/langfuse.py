"""Langfuse 的具体资源与 fail-open completion tracing 边界。"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import logging
from typing import Any

from langfuse import Langfuse, propagate_attributes
from langfuse.langchain import CallbackHandler

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LangfuseResources:
    """同一进程生命周期共享的 Langfuse client 与 LangChain handler。"""

    client: Any
    handler: Any


def create_langfuse_resources(settings: Any) -> LangfuseResources | None:
    """从显式 Settings 创建资源；配置不完整或初始化失败时禁用 tracing。"""

    public_key = _clean(getattr(settings, "langfuse_public_key", None))
    secret_key = _clean(getattr(settings, "langfuse_secret_key", None))
    base_url = _clean(getattr(settings, "langfuse_base_url", None))
    if public_key is None or secret_key is None or base_url is None:
        logger.info("Langfuse tracing unavailable: incomplete configuration")
        return None

    try:
        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=base_url,
            environment=(
                _clean(getattr(settings, "langfuse_environment", None))
                or "development"
            ),
            release=(
                _clean(getattr(settings, "langfuse_release", None))
                or _clean(getattr(settings, "app_version", None))
            ),
        )
        handler = CallbackHandler(public_key=public_key)
    except Exception:
        logger.exception("Langfuse tracing initialization failed")
        return None
    return LangfuseResources(client=client, handler=handler)


@contextmanager
def completion_trace(
    resources: LangfuseResources | None,
    *,
    input: dict[str, Any],
    session_id: str,
    user_id: str,
    metadata: dict[str, str],
    tags: list[str],
) -> Iterator[Any | None]:
    """建立 completion 根 observation，且不允许 tracing 改变业务异常。"""

    if resources is None:
        yield None
        return

    try:
        observation_context = resources.client.start_as_current_observation(
            as_type="span",
            name="chat-completion",
            input=input,
        )
        span = observation_context.__enter__()
    except Exception:
        logger.exception("Langfuse completion trace start failed")
        yield None
        return

    attributes_context = None
    try:
        attributes_context = propagate_attributes(
            session_id=session_id,
            user_id=user_id,
            metadata=metadata,
            tags=tags,
        )
        attributes_context.__enter__()
    except Exception:
        logger.exception("Langfuse attribute propagation failed")
        attributes_context = None

    try:
        yield span
    except BaseException as business_error:
        _safe_context_exit(attributes_context, business_error)
        _safe_context_exit(observation_context, business_error)
        raise
    else:
        _safe_context_exit(attributes_context, None)
        _safe_context_exit(observation_context, None)


def safe_update_trace(span: Any | None, **kwargs: Any) -> None:
    """尽力更新根 observation；失败只记日志。"""

    if span is None:
        return
    try:
        span.update(**kwargs)
    except Exception:
        logger.exception("Langfuse trace update failed")


async def shutdown_langfuse(resources: LangfuseResources) -> None:
    """在线程中关闭 Langfuse exporter，关闭失败不传播到应用 lifespan。"""

    try:
        await asyncio.to_thread(resources.client.shutdown)
    except Exception:
        logger.exception("Langfuse shutdown failed")


def _safe_context_exit(context: Any | None, error: BaseException | None) -> None:
    """关闭 Langfuse context，但忽略其 suppress 返回值并保留业务异常。"""

    if context is None:
        return
    try:
        context.__exit__(
            type(error) if error is not None else None,
            error,
            error.__traceback__ if error is not None else None,
        )
    except Exception:
        logger.exception("Langfuse context cleanup failed")


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None
