"""Chat completion 分布式锁的异步所有权操作。"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ConversationBusy(Exception):
    """同一 conversation 已有正在执行的 completion。"""


class ConversationLockUnavailable(Exception):
    """Redis 锁基础设施不可用。"""


async def acquire_completion_lock(
    lock_factory: Any,
    *,
    conversation_id: int,
) -> Any:
    """非阻塞获取 conversation 锁，并把同步 Redis I/O 移出事件循环。"""

    lock = lock_factory(conversation_id=conversation_id)
    try:
        acquired = await asyncio.to_thread(lock.acquire, blocking=False)
    except Exception as exc:
        raise ConversationLockUnavailable() from exc
    if not acquired:
        raise ConversationBusy()
    return lock


async def release_completion_lock(lock: Any) -> None:
    """释放 conversation 锁；失败时记录并依赖 expiry 最终回收。"""

    try:
        await asyncio.to_thread(lock.release)
    except Exception:
        logger.exception("failed to release chat completion lock")
