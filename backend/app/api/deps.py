"""API 层运行时初始化与请求期配置访问器。"""

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from app.core.config import Settings, get_request_settings
from app.modules.document.runtime import DocumentRuntime


def get_config() -> Settings:
    """返回请求期配置对象，读取失败时降级为 503。"""

    try:
        return get_request_settings()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Configuration not available") from exc


def get_document_runtime(request: Request) -> DocumentRuntime:
    """返回文档模块运行时资源，缺失时返回 503。"""

    document_runtime = getattr(request.app.state, "document_runtime", None)
    if document_runtime is None:
        raise HTTPException(
            status_code=503,
            detail="Document runtime not available",
        )
    return document_runtime


@asynccontextmanager
async def document_runtime(
    application: FastAPI,
    settings: Settings,
) -> AsyncGenerator[None, None]:
    """初始化并释放文档模块所需的启动期单例资源。"""

    from app.db.session import close_engine, get_session_factory, init_engine
    from app.infrastructure.magika import get_magika_client
    from app.infrastructure.mineru import create_mineru_client
    from app.infrastructure.minio import ensure_minio_bucket, get_minio_client
    from app.modules.document.repository import DocumentRepository
    from app.modules.document.storage import DocumentObjectStorage

    async with AsyncExitStack() as stack:
        await init_engine(settings.database_url)
        stack.push_async_callback(close_engine)

        mineru_client = create_mineru_client(settings)
        stack.push_async_callback(mineru_client.aclose)

        minio_client = get_minio_client()
        await ensure_minio_bucket(minio_client, settings.minio_bucket)

        storage = DocumentObjectStorage(
            client=minio_client,
            bucket=settings.minio_bucket,
            public_base_url=settings.minio_public_base_url,
        )

        application.state.document_runtime = DocumentRuntime(
            repository=DocumentRepository(get_session_factory()),
            storage=storage,
            file_detector=get_magika_client(),
            mineru_client=mineru_client,
        )
        stack.callback(_discard_app_state_attr, application, "document_runtime")

        yield


def _discard_app_state_attr(application: FastAPI, attr: str) -> None:
    """删除 app.state 上的临时属性，缺失时忽略。"""

    if hasattr(application.state, attr):
        delattr(application.state, attr)

