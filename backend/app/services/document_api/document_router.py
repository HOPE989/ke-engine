"""文档上传 HTTP 路由与错误响应映射。"""

from dataclasses import replace
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    UploadFile,
    status,
)

from app.common.response import APIResponse, success_response
from app.contracts.document.http import DocumentChunkRequest, DocumentChunkResponse, DocumentMetadata
from app.core.config import Settings
from app.core.exceptions import AppException
from app.infrastructure.redis import data_query_upload_lock, document_chunking_lock
from app.services.document_api.deps import DocumentApiDeps, get_config, get_document_deps
from app.domains.document.shared.errors import (
    ChunkLockUnavailable,
    ChunkPersistenceFailed,
    ChunkSplittingFailed,
    ConvertedMarkdownInvalid,
    ConvertedMarkdownUnavailable,
    DataQueryTableNameConflict,
    DataQueryUploadBusy,
    DataQueryUploadLockUnavailable,
    DocumentNotFound,
    DocumentStateConflict,
    DocumentStorageFailed,
    DocumentVectorStorageDispatchFailed,
    UnsupportedDocumentFileType,
)
from app.domains.document.components.validators import (
    DocumentFileTooLarge,
    InvalidDocumentChunkRequest,
    InvalidDocumentUpload,
    validate_document_chunk_request,
    validate_document_upload,
)
from app.domains.document.services.chunking import chunk_document
from app.domains.document.services.upload import upload_document
from app.domains.document.services.vectorization import request_document_vector_storage

router = APIRouter()


def _document_metadata_from_record(record: Any) -> DocumentMetadata:
    """把持久化记录转换为 HTTP 契约，避免 JSON 大整数精度风险。"""

    return DocumentMetadata(
        doc_id=str(record.doc_id),
        doc_title=record.doc_title,
        upload_user=record.upload_user,
        accessible_by=record.accessible_by,
        doc_url=record.doc_url,
        converted_doc_url=record.converted_doc_url,
        status=record.status,
    )


@router.post(
    "/upload",
    response_model=APIResponse[DocumentMetadata],
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document_endpoint(
    file: Annotated[UploadFile, File()],
    upload_user: Annotated[str, Form()],
    accessible_by: Annotated[str, Form()],
    knowledge_base_type: Annotated[str, Form(alias="knowledgeBaseType")],
    settings: Annotated[Settings, Depends(get_config)],
    document_deps: Annotated[DocumentApiDeps, Depends(get_document_deps)],
    description: Annotated[str, Form()] = "",
    table_name: Annotated[str | None, Form(alias="tableName")] = None,
    is_override: Annotated[bool | None, Form(alias="isOverride")] = None,
) -> APIResponse[DocumentMetadata]:
    """接收 multipart 上传请求并返回文档转换后的元数据。"""

    try:
        # 1. HTTP 边界先完成字段、文件名、大小和内容读取校验。
        validated_upload = await validate_document_upload(
            file=file,
            upload_user=upload_user,
            accessible_by=accessible_by,
            description=description,
            knowledge_base_type=knowledge_base_type,
            max_upload_size_mb=settings.max_upload_size_mb,
            table_name=table_name,
            is_override=is_override,
        )
    except DocumentFileTooLarge as exc:
        raise AppException("file too large", status.HTTP_413_CONTENT_TOO_LARGE) from exc
    except InvalidDocumentUpload as exc:
        raise AppException("invalid upload request", status.HTTP_400_BAD_REQUEST) from exc

    try:
        # 2. 业务编排交给 workflow，router 只负责 HTTP 依赖和异常映射。
        metadata = await _run_upload_with_optional_data_query_lock(
            upload=validated_upload,
            settings=settings,
            document_deps=document_deps,
        )
    except UnsupportedDocumentFileType as exc:
        raise AppException("unsupported file type", status.HTTP_415_UNSUPPORTED_MEDIA_TYPE) from exc
    except DataQueryTableNameConflict as exc:
        raise AppException("table name conflict", status.HTTP_409_CONFLICT) from exc
    except DataQueryUploadBusy as exc:
        raise AppException("data query upload busy", status.HTTP_409_CONFLICT) from exc
    except DataQueryUploadLockUnavailable as exc:
        raise AppException(
            "data query upload lock unavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    except DocumentStorageFailed as exc:
        raise AppException("document storage failed", status.HTTP_502_BAD_GATEWAY) from exc
    except DocumentStateConflict as exc:
        raise AppException("document state conflict", status.HTTP_409_CONFLICT) from exc

    return success_response(metadata)


async def _run_upload_with_optional_data_query_lock(
    *,
    upload,
    settings: Settings,
    document_deps: DocumentApiDeps,
) -> DocumentMetadata:
    if upload.knowledge_base_type == "DATA_QUERY":
        upload = replace(
            upload,
            data_query_upload_lock_factory=lambda: data_query_upload_lock(
                redis_client=document_deps.redis_client,
                namespace=upload.upload_user,
                expire_seconds=settings.document_convert_lock_expire_seconds,
            ),
        )

    return await upload_document(
        upload=upload,
        document_repository=document_deps.repository,
        storage=document_deps.storage,
        file_detector=document_deps.file_detector,
        id_generator=document_deps.id_generator,
        conversion_dispatcher=document_deps.conversion_dispatcher,
    )


@router.post(
    "/{doc_id}/chunk",
    response_model=APIResponse[DocumentChunkResponse],
)
async def chunk_document_endpoint(
    doc_id: int,
    request: DocumentChunkRequest,
    settings: Annotated[Settings, Depends(get_config)],
    document_deps: Annotated[DocumentApiDeps, Depends(get_document_deps)],
) -> APIResponse[DocumentChunkResponse]:
    """同步切分一个已转换文档。"""

    try:
        validated_request = validate_document_chunk_request(request)
    except InvalidDocumentChunkRequest as exc:
        raise AppException("invalid chunk request", status.HTTP_400_BAD_REQUEST) from exc

    lock = document_chunking_lock(
        redis_client=document_deps.redis_client,
        doc_id=doc_id,
        expire_seconds=settings.document_convert_lock_expire_seconds,
    )
    try:
        response = await chunk_document(
            doc_id=doc_id,
            document_repository=document_deps.repository,
            storage=document_deps.storage,
            id_generator=document_deps.id_generator,
            lock=lock,
            chunk_size=validated_request.chunk_size,
            overlap=validated_request.overlap,
            splitter_factory=document_deps.splitter_factory,
            embed_store_dispatcher=document_deps.embed_store_dispatcher,
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
    document_deps: Annotated[DocumentApiDeps, Depends(get_document_deps)],
) -> APIResponse[None]:
    """手动派发一个已切分文档的向量存储任务。

    HTTP 层只做依赖注入和错误映射。实际状态校验与 Kafka 派发由 workflow 完成，确保这个
    endpoint 不会在请求线程里执行 embedding 或 Elasticsearch 写入。
    """

    try:
        # 1. workflow 负责判断缺失、非 CHUNKED、已 VECTOR_STORED 等业务状态。
        await request_document_vector_storage(
            doc_id=doc_id,
            document_repository=document_deps.repository,
            embed_store_dispatcher=document_deps.embed_store_dispatcher,
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
    document_deps: Annotated[DocumentApiDeps, Depends(get_document_deps)],
) -> APIResponse[DocumentMetadata]:
    """查询文档当前元数据。"""

    document = await document_deps.repository.get_document(doc_id=doc_id)
    if document is None:
        raise AppException("document not found", status.HTTP_404_NOT_FOUND)
    return success_response(_document_metadata_from_record(document))
