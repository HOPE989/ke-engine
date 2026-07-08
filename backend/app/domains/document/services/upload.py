"""文档上传工作流。"""

import logging
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.contracts.document.http import DocumentMetadata
from app.domains.document.components.storage_keys import original_object_key
from app.domains.document.shared.errors import (
    DataQueryUploadBusy,
    DataQueryUploadLockUnavailable,
    DocumentStorageFailed,
    UnsupportedDocumentFileType,
)
from app.domains.document.shared.file_types import DocumentFileType, detect_document_file_type
from app.domains.document.shared.models import DocumentStatus, KnowledgeBaseType

logger = logging.getLogger(__name__)


async def upload_document(
    *,
    upload: Any,
    document_repository: Any,
    storage: Any,
    file_detector: Any,
    id_generator: Any,
    conversion_dispatcher: Any,
) -> Any:
    """处理单次文档上传，返回可持久消费的文档元数据。"""

    # 1. 先检测文件类型，避免不支持的内容产生数据库或对象存储副作用。
    file_type = await run_in_threadpool(
        detect_document_file_type,
        filename=upload.safe_filename,
        content=upload.content,
        upload_content_type=upload.content_type,
        magika_client=file_detector,
    )
    if upload.knowledge_base_type == KnowledgeBaseType.DATA_QUERY.value:
        # DATA_QUERY 当前只支持结构化 spreadsheet。非 Excel/CSV 在创建 document/table_meta
        # 之前拒绝，避免无效上传占用逻辑表名。
        if file_type not in {DocumentFileType.EXCEL, DocumentFileType.CSV}:
            raise UnsupportedDocumentFileType()
        # 上传阶段负责 tableName 占位和 override 决策，必须在 namespace 锁内完成。
        return await _run_with_data_query_upload_lock(
            lock_factory=upload.data_query_upload_lock_factory,
            operation=lambda: _upload_data_query_document(
                upload=upload,
                file_type=file_type.value,
                document_repository=document_repository,
                storage=storage,
                id_generator=id_generator,
                conversion_dispatcher=conversion_dispatcher,
            ),
        )

    # 2. 先生成 doc_id，再创建 INIT 行；对象存储 key 依赖这个稳定 ID。
    doc_id = id_generator.next_id()
    document = await document_repository.create_init_document(
        doc_id=doc_id,
        doc_title=upload.doc_title,
        upload_user=upload.upload_user,
        accessible_by=upload.accessible_by,
        description=upload.description,
        knowledge_base_type=upload.knowledge_base_type,
        file_type=file_type,
    )

    object_key = original_object_key(
        doc_id=document.doc_id,
        safe_filename=upload.safe_filename,
    )
    try:
        # 3. 上传原文；bucket 在应用启动期已完成初始化。
        doc_url = await storage.upload_bytes(
            object_key=object_key,
            content=upload.content,
            content_type="application/octet-stream",
        )
    except Exception as exc:
        raise DocumentStorageFailed() from exc

    # 4. 原文上传成功后推进生命周期并保存稳定 URL。
    await document_repository.mark_uploaded(doc_id=document.doc_id, doc_url=doc_url)

    try:
        await conversion_dispatcher.dispatch(document.doc_id)
    except Exception:
        logger.exception("failed to dispatch document conversion event", extra={"doc_id": document.doc_id})

    return DocumentMetadata(
        doc_id=str(document.doc_id),
        doc_title=upload.doc_title,
        upload_user=upload.upload_user,
        accessible_by=upload.accessible_by,
        doc_url=doc_url,
        converted_doc_url=None,
        status=DocumentStatus.UPLOADED.value,
    )


async def _upload_data_query_document(
    *,
    upload: Any,
    file_type: str,
    document_repository: Any,
    storage: Any,
    id_generator: Any,
    conversion_dispatcher: Any,
) -> DocumentMetadata:
    """预留 DATA_QUERY 表元数据并保存原始 spreadsheet 文件。"""

    # 1. document 和 table_meta 使用独立 Snowflake ID；table_meta 先作为逻辑表名占位。
    doc_id = id_generator.next_id()
    table_meta_id = id_generator.next_id()
    extension = {
        "tableName": upload.table_name,
        "isOverride": upload.is_override,
    }
    document = await document_repository.create_data_query_document_with_table_reservation(
        doc_id=doc_id,
        table_meta_id=table_meta_id,
        doc_title=upload.doc_title,
        upload_user=upload.upload_user,
        accessible_by=upload.accessible_by,
        description=upload.description,
        knowledge_base_type=upload.knowledge_base_type,
        file_type=file_type,
        namespace=upload.upload_user,
        table_name=upload.table_name,
        is_override=upload.is_override,
        extension=extension,
    )

    # 2. 原始文件仍按 document 原有对象 key 规则存储，worker 后续从这里下载。
    object_key = original_object_key(
        doc_id=document.doc_id,
        safe_filename=upload.safe_filename,
    )
    try:
        doc_url = await storage.upload_bytes(
            object_key=object_key,
            content=upload.content,
            content_type="application/octet-stream",
        )
    except Exception as exc:
        # 3. 新文件尚未上传成功时，释放本次新建占位；override 已删除的旧数据不恢复。
        await document_repository.delete_data_query_reservation(document_id=document.doc_id)
        raise DocumentStorageFailed() from exc

    # 4. 对象存储成功后推进到 UPLOADED，表示异步导入 worker 可以消费。
    await document_repository.mark_uploaded(doc_id=document.doc_id, doc_url=doc_url)

    try:
        # 5. dispatch 失败不回滚上传结果，保持和现有文档链路一致，由后续补偿/重试处理。
        await conversion_dispatcher.dispatch(document.doc_id)
    except Exception:
        logger.exception(
            "failed to dispatch document conversion event",
            extra={"doc_id": document.doc_id},
        )

    return DocumentMetadata(
        doc_id=str(document.doc_id),
        doc_title=upload.doc_title,
        upload_user=upload.upload_user,
        accessible_by=upload.accessible_by,
        doc_url=doc_url,
        converted_doc_url=None,
        status=DocumentStatus.UPLOADED.value,
    )


async def _run_with_data_query_upload_lock(*, lock_factory: Any, operation: Any) -> Any:
    """以非等待方式持有 DATA_QUERY namespace 上传锁并执行操作。"""

    if lock_factory is None:
        raise DataQueryUploadLockUnavailable()
    try:
        lock = lock_factory()
        acquired = lock.acquire(blocking=False)
    except Exception as exc:
        raise DataQueryUploadLockUnavailable() from exc
    if not acquired:
        raise DataQueryUploadBusy()
    try:
        return await operation()
    finally:
        try:
            lock.release()
        except Exception:
            # operation 已经可能完成数据库、对象存储和 Kafka 副作用；release 失败只记录，
            # 不把已经 accepted 的上传伪装成 503。
            logger.exception("failed to release data query upload lock")
