"""Agent API 请求依赖。"""

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class AgentApiDeps:
    """Agent API 长生命周期依赖集合。"""

    settings: Any | None = None


def get_config(request: Request) -> Settings:
    """返回 Agent API 启动期配置快照。"""

    try:
        return request.app.state.settings
    except AttributeError as exc:
        raise HTTPException(status_code=503, detail="Application settings not available") from exc


def get_agent_deps(request: Request) -> AgentApiDeps:
    """返回 Agent API 依赖集合，未装配时返回空依赖。"""

    deps = getattr(request.app.state, "agent_deps", None)
    if deps is None:
        return AgentApiDeps(settings=getattr(request.app.state, "settings", None))
    return deps
