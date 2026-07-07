"""文档后台解析流程。"""

from typing import Any

from app.modules.document.errors import (
    DocumentConversionFailed,
    DocumentStateConflict,
    DocumentStateRollbackFailed,
)
from app.modules.document.data_query_spreadsheet import ingest_data_query_spreadsheet_document
from app.modules.document.file_types import DocumentFileType
from app.modules.document.models import DocumentStatus, KnowledgeBaseType


DATA_QUERY_SPREADSHEET_FILE_TYPES = {
    DocumentFileType.EXCEL.value,
    DocumentFileType.CSV.value,
}


async def convert_uploaded_document(
    *,
    doc_id: int,
    document_repository: Any,
    storage: Any,
    mineru_client: Any,
    converter_factory: Any,
    image_describer: Any | None = None,
) -> None:
    """处理一条已上传文档的异步转换任务。

    DOCUMENT_SEARCH 仍沿用原文档链路：UPLOADED -> CONVERTING -> CONVERTED。
    DATA_QUERY Excel/CSV 则表示结构化表格导入，不产出 converted_doc_url，也不进入
    chunk/vector 阶段，成功后由导入事务直接推进到 STORED。

    `converter_factory` 由 worker 进程启动期创建并注入，转换热路径只使用已装配好的
    factory，不负责初始化 converter 注册表。
    """

    document = await document_repository.get_document(doc_id)
    if document is None:
        return
    if _is_data_query_spreadsheet_document(document):
        # DATA_QUERY spreadsheet 的终态是 STORED；Kafka 重投成功消息时直接幂等返回。
        if document.status == DocumentStatus.STORED.value:
            return
        # 非 UPLOADED 状态不是当前 worker 可以处理的阶段，保持终端 no-op。
        if document.status != DocumentStatus.UPLOADED.value:
            return
        # DATA_QUERY 不设置 CONVERTING/CONVERTED，中间状态由数据库事务保证原子性。
        await ingest_data_query_spreadsheet_document(
            document=document,
            document_repository=document_repository,
            storage=storage,
        )
        return
    if document.status != DocumentStatus.UPLOADED.value:
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
            converter_factory=converter_factory,
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
    converter_factory: Any,
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
            converter_factory=converter_factory,
            image_describer=image_describer,
        )
    finally:
        lock.release()


async def _convert_document_content(
    *,
    document: Any,
    storage: Any,
    mineru_client: Any,
    converter_factory: Any,
    image_describer: Any | None = None,
) -> str:
    return await converter_factory.convert_document(
        document=document,
        storage=storage,
        mineru_client=mineru_client,
        image_describer=image_describer,
    )


def _is_data_query_spreadsheet_document(document: Any) -> bool:
    """判断文档是否应进入 DATA_QUERY 关系型导入路径。"""

    return (
        getattr(document, "knowledge_base_type", None) == KnowledgeBaseType.DATA_QUERY.value
        and str(getattr(document, "file_type", "")) in DATA_QUERY_SPREADSHEET_FILE_TYPES
    )


async def _rollback_to_uploaded(*, document_repository: Any, doc_id: int) -> None:
    try:
        await document_repository.rollback_to_uploaded(doc_id=doc_id)
    except Exception as exc:
        raise DocumentStateRollbackFailed() from exc
