"""Chat API 应用装配。"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.identity import IdentityMiddleware, MockIdentityProvider
from app.services.chat_api.deps import application_lifespan_resources


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    async with application_lifespan_resources(application, settings):
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    application = FastAPI(
        title=f"{settings.app_name}-chat-api",
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
    )
    application.add_middleware(
        IdentityMiddleware,
        provider=MockIdentityProvider(),
        public_paths={"/health"},
    )
    register_exception_handlers(application)

    @application.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "service": f"{settings.app_name}-chat-api"}

    return application
