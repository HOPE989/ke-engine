"""文档后台解析流程。"""

from typing import Any

from app.modules.document.errors import (
    DocumentConversionFailed,
    DocumentStateConflict,
    DocumentStateRollbackFailed,
)
from app.modules.document.converters import default_document_converter_factory
from app.modules.document.models import DocumentStatus


async def convert_uploaded_document(
    *,
    doc_id: int,
    document_repository: Any,
    storage: Any,
    mineru_client: Any,
    image_describer: Any | None = None,
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
            image_describer=image_describer,
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
    image_describer: Any | None = None,
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
            image_describer=image_describer,
        )
    finally:
        lock.release()


async def _convert_document_content(
    *,
    document: Any,
    storage: Any,
    mineru_client: Any,
    image_describer: Any | None = None,
) -> str:
    return await default_document_converter_factory.convert_document(
        document=document,
        storage=storage,
        mineru_client=mineru_client,
        image_describer=image_describer,
    )


async def _rollback_to_uploaded(*, document_repository: Any, doc_id: int) -> None:
    try:
        await document_repository.rollback_to_uploaded(doc_id=doc_id)
    except Exception as exc:
        raise DocumentStateRollbackFailed() from exc
