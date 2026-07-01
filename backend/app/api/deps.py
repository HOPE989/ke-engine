"""API 层运行时初始化与 app.state 单例资源访问器。"""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import TypeVar, cast

from fastapi import FastAPI, HTTPException, Request

from app.core.config import Settings, get_settings

T = TypeVar("T")


def get_config() -> Settings:
    """返回请求期配置对象，读取失败时降级为 503。"""

    try:
        return get_settings()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Configuration not available") from exc


@asynccontextmanager
async def document_upload_runtime(
    application: FastAPI,
    settings: Settings,
) -> AsyncGenerator[None, None]:
    """初始化并释放文档上传所需的启动期单例资源。"""

    from app.db.session import close_engine, get_session_factory, init_engine
    from app.infrastructure.magika import get_magika_client
    from app.infrastructure.mineru import close_mineru_client
    from app.infrastructure.minio import get_minio_client
    from app.modules.document.repository import DocumentRepository
    from app.modules.document.storage import DocumentObjectStorage

    await init_engine(settings.database_url)
    application.state.document_repository = DocumentRepository(get_session_factory())
    application.state.document_storage = DocumentObjectStorage(
        client=get_minio_client(),
        bucket=settings.minio_bucket,
        public_base_url=settings.minio_public_base_url,
    )
    application.state.document_file_detector = get_magika_client()
    try:
        yield
    finally:
        await close_mineru_client(application)
        await close_engine()


def _require(attr: str, label: str) -> Callable[[Request], T]:
    """创建读取 app.state 指定资源的 FastAPI 依赖函数。"""

    def dependency(request: Request) -> T:
        """返回 app.state 上的必需资源，缺失时抛出 503。"""

        value = getattr(request.app.state, attr, None)
        if value is None:
            raise HTTPException(status_code=503, detail=f"{label} not available")
        return cast(T, value)

    dependency.__name__ = dependency.__qualname__ = f"get_{attr}"
    return dependency


get_document_repository: Callable[[Request], object] = _require(
    "document_repository",
    "Document repository",
)
get_document_storage: Callable[[Request], object] = _require(
    "document_storage",
    "Document storage",
)
get_document_file_detector: Callable[[Request], object] = _require(
    "document_file_detector",
    "Document file detector",
)

