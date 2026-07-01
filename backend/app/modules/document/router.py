"""文档上传 HTTP 路由与错误响应映射。"""

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    UploadFile,
    status,
)

from app.api.deps import get_config, get_document_runtime
from app.common.response import APIResponse, success_response
from app.core.config import Settings
from app.core.exceptions import AppException
from app.modules.document.errors import (
    DocumentConversionFailed,
    DocumentStateConflict,
    DocumentStateRollbackFailed,
    DocumentStorageFailed,
)
from app.modules.document.runtime import DocumentRuntime
from app.modules.document.schemas import (
    DocumentFileTooLarge,
    DocumentMetadata,
    InvalidDocumentUpload,
    validate_document_upload,
)
from app.modules.document.workflow import upload_document

router = APIRouter()


@router.post("/upload", response_model=APIResponse[DocumentMetadata])
async def upload_document_endpoint(
    file: Annotated[UploadFile, File()],
    upload_user: Annotated[str, Form()],
    accessible_by: Annotated[str, Form()],
    settings: Annotated[Settings, Depends(get_config)],
    document_runtime: Annotated[DocumentRuntime, Depends(get_document_runtime)],
) -> APIResponse[DocumentMetadata]:
    """接收 multipart 上传请求并返回文档转换后的元数据。"""

    try:
        # 1. HTTP 边界先完成字段、文件名、大小和内容读取校验。
        validated_upload = await validate_document_upload(
            file=file,
            upload_user=upload_user,
            accessible_by=accessible_by,
            max_upload_size_mb=settings.max_upload_size_mb,
        )
    except DocumentFileTooLarge as exc:
        raise AppException("file too large", status.HTTP_413_CONTENT_TOO_LARGE) from exc
    except InvalidDocumentUpload as exc:
        raise AppException("invalid upload request", status.HTTP_400_BAD_REQUEST) from exc

    try:
        # 2. 业务编排交给 workflow，router 只负责 HTTP 依赖和异常映射。
        metadata = await upload_document(
            upload=validated_upload,
            document_repository=document_runtime.repository,
            storage=document_runtime.storage,
            file_detector=document_runtime.file_detector,
            mineru_client=document_runtime.mineru_client,
        )
    except DocumentStorageFailed as exc:
        raise AppException("document storage failed", status.HTTP_502_BAD_GATEWAY) from exc
    except DocumentStateConflict as exc:
        raise AppException("document state conflict", status.HTTP_409_CONFLICT) from exc
    except DocumentStateRollbackFailed as exc:
        raise AppException("document state rollback failed", status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    except DocumentConversionFailed as exc:
        raise AppException("document conversion failed", status.HTTP_502_BAD_GATEWAY) from exc

    return success_response(metadata)
