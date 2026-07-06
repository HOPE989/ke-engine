"""FastAPI 应用创建、路由注册与运行时资源生命周期入口。"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.deps import application_lifespan_resources
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """启动期初始化共享基础设施，关闭期统一释放资源。"""

    startup_settings = get_settings()
    async with application_lifespan_resources(application, startup_settings):
        yield


def create_app() -> FastAPI:
    """创建 FastAPI 应用并挂载统一异常处理、路由和健康检查。"""

    settings = get_settings()
    configure_logging()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
    )
    register_exception_handlers(application)
    application.include_router(api_router, prefix=settings.api_v1_prefix)

    @application.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """返回应用存活状态，供本地开发和部署探针使用。"""

        return {"status": "ok", "service": settings.app_name}

    return application


app = create_app()

