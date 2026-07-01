"""文档后台解析流程。"""

from typing import Any

from app.modules.document.errors import (
    DocumentConversionFailed,
    DocumentStateConflict,
    DocumentStateRollbackFailed,
)
from app.modules.document.file_types import DocumentFileType
from app.modules.document.models import DocumentStatus
from app.modules.document.schemas import ValidatedDocumentUpload
from app.modules.document.storage import original_object_key
from app.modules.document.workflow import convert_pdf_document


def _file_type_value(file_type: DocumentFileType | str) -> str:
    if isinstance(file_type, DocumentFileType):
        return file_type.value
    return str(file_type)


async def convert_uploaded_document(
    *,
    doc_id: int,
    document_repository: Any,
    storage: Any,
    mineru_client: Any,
) -> None:
    """把一个 UPLOADED 文档自动解析推进到 CONVERTED。"""

    document = await document_repository.get_document(doc_id)
    if document is None or document.status != DocumentStatus.UPLOADED.value:
        return

    try:
        await document_repository.start_converting(doc_id=doc_id)
    except DocumentStateConflict:
        return

    try:
        converted_doc_url = await _convert_document_content(
            document=document,
            storage=storage,
            mineru_client=mineru_client,
        )
    except DocumentConversionFailed:
        await _rollback_to_uploaded(document_repository=document_repository, doc_id=doc_id)
        raise
    except Exception as exc:
        await _rollback_to_uploaded(document_repository=document_repository, doc_id=doc_id)
        raise DocumentConversionFailed() from exc

    await document_repository.mark_converted(
        doc_id=doc_id,
        converted_doc_url=converted_doc_url,
        expected_status=DocumentStatus.CONVERTING,
    )


async def convert_document_with_lock(
    *,
    doc_id: int,
    document_repository: Any,
    storage: Any,
    mineru_client: Any,
    lock: Any,
) -> None:
    """在单文档 Redis 锁内执行解析，拿不到锁时直接跳过。"""

    if not lock.acquire(blocking=False):
        return
    try:
        await convert_uploaded_document(
            doc_id=doc_id,
            document_repository=document_repository,
            storage=storage,
            mineru_client=mineru_client,
        )
    finally:
        lock.release()


async def _convert_document_content(
    *,
    document: Any,
    storage: Any,
    mineru_client: Any,
) -> str:
    file_type = _file_type_value(document.file_type)
    if file_type == DocumentFileType.PLAIN_TEXT.value:
        if not document.doc_url:
            raise DocumentConversionFailed()
        return document.doc_url

    if file_type != DocumentFileType.PDF.value:
        raise DocumentConversionFailed()

    object_key = original_object_key(
        doc_id=document.doc_id,
        safe_filename=document.doc_title,
    )
    try:
        content = await storage.download_bytes(object_key=object_key)
    except Exception as exc:
        raise DocumentConversionFailed() from exc

    upload = ValidatedDocumentUpload(
        doc_title=document.doc_title,
        safe_filename=document.doc_title,
        upload_user=document.upload_user,
        accessible_by=document.accessible_by,
        content_type="application/pdf",
        content=content,
        size_bytes=len(content),
    )
    return await convert_pdf_document(
        doc_id=document.doc_id,
        upload=upload,
        storage=storage,
        mineru_client=mineru_client,
    )


async def _rollback_to_uploaded(*, document_repository: Any, doc_id: int) -> None:
    try:
        await document_repository.rollback_to_uploaded(doc_id=doc_id)
    except Exception as exc:
        raise DocumentStateRollbackFailed() from exc
