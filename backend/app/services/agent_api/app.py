"""Agent API 应用装配。"""

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.services.agent_api.router import router


def create_app() -> FastAPI:
    """创建只暴露 Agent/聊天能力的 FastAPI 应用。"""

    settings = get_settings()
    configure_logging()

    application = FastAPI(
        title=f"{settings.app_name}-agent-api",
        version=settings.app_version,
        debug=settings.debug,
    )
    register_exception_handlers(application)
    application.include_router(router, prefix=settings.api_v1_prefix)

    @application.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "service": f"{settings.app_name}-agent-api"}

    return application
