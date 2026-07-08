"""Document API 应用装配。"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.services.document_api.deps import application_lifespan_resources
from app.services.document_api.router import router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """启动期初始化 Document API 需要的共享资源。"""

    startup_settings = get_settings()
    async with application_lifespan_resources(application, startup_settings):
        yield


def create_app() -> FastAPI:
    """创建只暴露文档/知识资产能力的 FastAPI 应用。"""

    settings = get_settings()
    configure_logging()

    application = FastAPI(
        title=f"{settings.app_name}-document-api",
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
    )
    register_exception_handlers(application)
    application.include_router(router, prefix=settings.api_v1_prefix)

    @application.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "service": f"{settings.app_name}-document-api"}

    return application
