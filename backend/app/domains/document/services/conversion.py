"""文档后台解析流程。"""

import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.domains.document.shared.errors import (
    DocumentConversionFailed,
    DocumentStateConflict,
    DocumentStateRollbackFailed,
)
from app.domains.document.components.markdown_assets import (
    IMAGE_PARSE_ERROR_DESCRIPTION,
    IMAGE_SUFFIXES,
    MARKDOWN_SUFFIXES,
    extract_mineru_zip,
    image_content_type,
    rewrite_markdown_image_links,
    select_markdown_path,
)
from app.domains.document.components.storage_keys import (
    asset_object_key,
    converted_markdown_object_key,
)
from app.domains.document.services.data_query import ingest_data_query_spreadsheet_document
from app.domains.document.shared.file_types import DocumentFileType
from app.domains.document.shared.models import DocumentStatus, KnowledgeBaseType

logger = logging.getLogger(__name__)


DATA_QUERY_SPREADSHEET_FILE_TYPES = {
    DocumentFileType.EXCEL.value,
    DocumentFileType.CSV.value,
}


async def convert_mineru_document(
    *,
    doc_id: int,
    upload: Any,
    storage: Any,
    mineru_client: Any,
    image_describer: Any | None = None,
) -> str:
    """调用 MinerU 转换文件，上传图片和最终 Markdown，并返回 Markdown URL。"""

    try:
        zip_bytes = await mineru_client.request_zip(
            filename=upload.safe_filename,
            content=upload.content,
        )

        with TemporaryDirectory(prefix="mineru-") as temp_dir:
            root = Path(temp_dir)
            extracted_paths = extract_mineru_zip(zip_bytes, root)
            markdown_paths = [
                path for path in extracted_paths if path.suffix.lower() in MARKDOWN_SUFFIXES
            ]
            selected_markdown_path = select_markdown_path(
                markdown_paths,
                Path(upload.safe_filename).stem,
            )
            ensure_image_describer_configured = getattr(
                image_describer,
                "ensure_configured",
                None,
            )
            if ensure_image_describer_configured is not None:
                ensure_image_describer_configured()

            image_urls: dict[str, str] = {}
            image_descriptions: dict[str, str] = {}
            for image_path in extracted_paths:
                if image_path.suffix.lower() not in IMAGE_SUFFIXES:
                    continue

                image_key = asset_object_key(doc_id=doc_id, image_filename=image_path.name)
                try:
                    image_bytes = (root / image_path).read_bytes()
                    content_type = image_content_type(image_path)
                    image_url = await storage.upload_bytes(
                        object_key=image_key,
                        content=image_bytes,
                        content_type=content_type,
                    )
                except Exception:
                    logger.warning(
                        "document image upload failed",
                        extra={"doc_id": doc_id, "image_target": image_path.as_posix()},
                    )
                    continue
                image_urls[image_path.as_posix()] = image_url
                image_urls[image_path.name] = image_url
                if image_describer is not None:
                    try:
                        description = await image_describer.describe_image(
                            filename=image_path.name,
                            content=image_bytes,
                            content_type=content_type,
                        )
                        alt_text = str(description).strip()
                        if not alt_text:
                            logger.warning(
                                "document image description failed",
                                extra={
                                    "doc_id": doc_id,
                                    "image_target": image_path.as_posix(),
                                },
                            )
                            alt_text = IMAGE_PARSE_ERROR_DESCRIPTION
                    except Exception:
                        logger.warning(
                            "document image description failed",
                            extra={"doc_id": doc_id, "image_target": image_path.as_posix()},
                        )
                        alt_text = IMAGE_PARSE_ERROR_DESCRIPTION
                    image_descriptions[image_path.as_posix()] = alt_text
                    image_descriptions[image_path.name] = alt_text

            markdown_text = (root / selected_markdown_path).read_text(encoding="utf-8")
            rewritten_markdown = rewrite_markdown_image_links(
                markdown_text,
                image_urls,
                image_descriptions=image_descriptions,
                on_missing_image=lambda reference: logger.warning(
                    "document image rewrite failed",
                    extra={"doc_id": doc_id, "image_target": reference.target},
                ),
            )

            return await storage.upload_bytes(
                object_key=converted_markdown_object_key(doc_id=doc_id),
                content=rewritten_markdown.encode(),
                content_type="text/markdown",
            )
    except DocumentConversionFailed:
        raise
    except Exception as exc:
        raise DocumentConversionFailed() from exc


async def convert_pdf_document(
    *,
    doc_id: int,
    upload: Any,
    storage: Any,
    mineru_client: Any,
    image_describer: Any | None = None,
) -> str:
    """转换 PDF 文件，上传图片和最终 Markdown，并返回 Markdown URL。"""

    return await convert_mineru_document(
        doc_id=doc_id,
        upload=upload,
        storage=storage,
        mineru_client=mineru_client,
        image_describer=image_describer,
    )


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
