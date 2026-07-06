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

from app.api.deps import DocumentRuntime, get_config, get_document_runtime
from app.common.response import APIResponse, success_response
from app.core.config import Settings
from app.core.exceptions import AppException
from app.infrastructure.redis_lock import document_chunking_lock
from app.modules.document.errors import (
    ChunkLockUnavailable,
    ChunkPersistenceFailed,
    ChunkSplittingFailed,
    ConvertedMarkdownInvalid,
    ConvertedMarkdownUnavailable,
    DocumentNotFound,
    DocumentStateConflict,
    DocumentStorageFailed,
    DocumentVectorStorageDispatchFailed,
)
from app.modules.document.schemas import (
    DocumentChunkRequest,
    DocumentChunkResponse,
    DocumentFileTooLarge,
    DocumentMetadata,
    InvalidDocumentUpload,
    InvalidDocumentChunkRequest,
    document_metadata_from_record,
    validate_document_chunk_request,
    validate_document_upload,
)
from app.modules.document.workflow import chunk_document, request_document_vector_storage, upload_document

router = APIRouter()


@router.post(
    "/upload",
    response_model=APIResponse[DocumentMetadata],
    status_code=status.HTTP_202_ACCEPTED,
)
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
            id_generator=document_runtime.id_generator,
            conversion_dispatcher=document_runtime.conversion_dispatcher,
        )
    except DocumentStorageFailed as exc:
        raise AppException("document storage failed", status.HTTP_502_BAD_GATEWAY) from exc
    except DocumentStateConflict as exc:
        raise AppException("document state conflict", status.HTTP_409_CONFLICT) from exc

    return success_response(metadata)


@router.post(
    "/{doc_id}/chunk",
    response_model=APIResponse[DocumentChunkResponse],
)
async def chunk_document_endpoint(
    doc_id: int,
    request: DocumentChunkRequest,
    settings: Annotated[Settings, Depends(get_config)],
    document_runtime: Annotated[DocumentRuntime, Depends(get_document_runtime)],
) -> APIResponse[DocumentChunkResponse]:
    """同步切分一个已转换文档。"""

    try:
        validated_request = validate_document_chunk_request(request)
    except InvalidDocumentChunkRequest as exc:
        raise AppException("invalid chunk request", status.HTTP_400_BAD_REQUEST) from exc

    lock = document_chunking_lock(
        redis_client=document_runtime.redis_client,
        doc_id=doc_id,
        expire_seconds=settings.document_convert_lock_expire_seconds,
    )
    try:
        response = await chunk_document(
            doc_id=doc_id,
            document_repository=document_runtime.repository,
            storage=document_runtime.storage,
            id_generator=document_runtime.id_generator,
            lock=lock,
            chunk_size=validated_request.chunk_size,
            overlap=validated_request.overlap,
            embed_store_dispatcher=document_runtime.embed_store_dispatcher,
        )
    except DocumentNotFound as exc:
        raise AppException("document not found", status.HTTP_404_NOT_FOUND) from exc
    except DocumentStateConflict as exc:
        raise AppException("document state conflict", status.HTTP_409_CONFLICT) from exc
    except ChunkLockUnavailable as exc:
        raise AppException("chunk lock unavailable", status.HTTP_503_SERVICE_UNAVAILABLE) from exc
    except ConvertedMarkdownUnavailable as exc:
        raise AppException("converted markdown unavailable", status.HTTP_502_BAD_GATEWAY) from exc
    except ConvertedMarkdownInvalid as exc:
        raise AppException("converted markdown invalid", 422) from exc
    except ChunkSplittingFailed as exc:
        raise AppException("chunk splitting failed", status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    except ChunkPersistenceFailed as exc:
        raise AppException("chunk persistence failed", status.HTTP_500_INTERNAL_SERVER_ERROR) from exc
    return success_response(response)


@router.post("/{doc_id}/embed-store", response_model=APIResponse[None])
async def embed_store_document_endpoint(
    doc_id: int,
    document_runtime: Annotated[DocumentRuntime, Depends(get_document_runtime)],
) -> APIResponse[None]:
    """手动派发一个已切分文档的向量存储任务。

    HTTP 层只做依赖注入和错误映射。实际状态校验与 Kafka 派发由 workflow 完成，确保这个
    endpoint 不会在请求线程里执行 embedding 或 Elasticsearch 写入。
    """

    try:
        # 1. workflow 负责判断缺失、非 CHUNKED、已 VECTOR_STORED 等业务状态。
        await request_document_vector_storage(
            doc_id=doc_id,
            document_repository=document_runtime.repository,
            embed_store_dispatcher=document_runtime.embed_store_dispatcher,
        )
    except DocumentNotFound as exc:
        raise AppException("document not found", status.HTTP_404_NOT_FOUND) from exc
    except DocumentStateConflict as exc:
        raise AppException("document state conflict", status.HTTP_409_CONFLICT) from exc
    except DocumentVectorStorageDispatchFailed as exc:
        raise AppException(
            "vector storage dispatch failed",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    return success_response(None)


@router.get("/{doc_id}", response_model=APIResponse[DocumentMetadata])
async def get_document_endpoint(
    doc_id: int,
    document_runtime: Annotated[DocumentRuntime, Depends(get_document_runtime)],
) -> APIResponse[DocumentMetadata]:
    """查询文档当前元数据。"""

    document = await document_runtime.repository.get_document(doc_id=doc_id)
    if document is None:
        raise AppException("document not found", status.HTTP_404_NOT_FOUND)
    return success_response(document_metadata_from_record(document))
