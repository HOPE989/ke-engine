"""MinerU HTTP client 的 app-state 生命周期管理。"""

from typing import Any

import httpx

from app.core.config import get_settings

MINERU_CLIENT_STATE_KEY = "mineru_client"


async def get_mineru_client(request: Any) -> httpx.AsyncClient:
    """从 FastAPI app.state 复用或创建 MinerU AsyncClient。"""

    # MinerU client 需要显式关闭，因此挂在 app.state 而不是 lru_cache。
    client = getattr(request.app.state, MINERU_CLIENT_STATE_KEY, None)
    if client is not None:
        return client

    settings = get_settings()
    client = httpx.AsyncClient(
        base_url=settings.mineru_base_url,
        timeout=settings.mineru_timeout_seconds,
    )
    setattr(request.app.state, MINERU_CLIENT_STATE_KEY, client)
    return client


async def close_mineru_client(app: Any) -> None:
    """关闭 app.state 中缓存的 MinerU AsyncClient。"""

    client = getattr(app.state, MINERU_CLIENT_STATE_KEY, None)
    if client is None:
        return

    await client.aclose()
    delattr(app.state, MINERU_CLIENT_STATE_KEY)
