"""文档上传与转换的应用工作流编排。"""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.modules.document.errors import (
    DocumentConversionFailed,
    DocumentStateRollbackFailed,
    DocumentStorageFailed,
)
from app.modules.document.file_types import DocumentFileType, detect_document_file_type
from app.modules.document.markdown import (
    IMAGE_SUFFIXES,
    MARKDOWN_SUFFIXES,
    extract_mineru_zip,
    image_content_type,
    rewrite_markdown_image_links,
    select_markdown_path,
)
from app.modules.document.mineru import request_mineru_zip
from app.modules.document.models import DocumentStatus
from app.modules.document.schemas import DocumentMetadata
from app.modules.document.storage import (
    asset_object_key,
    converted_markdown_object_key,
    original_object_key,
)


async def convert_pdf_document(
    *,
    doc_id: int,
    upload: Any,
    storage: Any,
    mineru_client: Any,
) -> str:
    """转换 PDF 文件，上传图片和最终 Markdown，并返回 Markdown URL。"""

    try:
        # 1. 请求 MinerU 产出 ZIP，后续所有解析都基于这个归档。
        zip_bytes = await request_mineru_zip(
            client=mineru_client,
            filename=upload.safe_filename,
            content=upload.content,
        )

        # 2. 在独立临时目录内安全解压并选择主 Markdown。
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

            # 3. 上传图片资源，并同时记录相对路径和文件名两种匹配键。
            image_urls: dict[str, str] = {}
            for image_path in extracted_paths:
                if image_path.suffix.lower() not in IMAGE_SUFFIXES:
                    continue

                image_key = asset_object_key(doc_id=doc_id, image_filename=image_path.name)
                image_url = await storage.upload_bytes(
                    object_key=image_key,
                    content=(root / image_path).read_bytes(),
                    content_type=image_content_type(image_path),
                )
                image_urls[image_path.as_posix()] = image_url
                image_urls[image_path.name] = image_url

            # 4. 重写 Markdown 图片链接后上传最终 Markdown。
            markdown_text = (root / selected_markdown_path).read_text(encoding="utf-8")
            rewritten_markdown = rewrite_markdown_image_links(markdown_text, image_urls)
            return await storage.upload_bytes(
                object_key=converted_markdown_object_key(doc_id=doc_id),
                content=rewritten_markdown.encode(),
                content_type="text/markdown",
            )
    except DocumentConversionFailed:
        raise
    except Exception as exc:
        raise DocumentConversionFailed() from exc


async def upload_document(
    *,
    upload: Any,
    document_repository: Any,
    storage: Any,
    file_detector: Any,
    mineru_client: Any,
) -> Any:
    """处理单次文档上传，返回可持久消费的文档元数据。"""

    # 1. 先检测文件类型，避免不支持的内容产生数据库或对象存储副作用。
    file_type = detect_document_file_type(
        filename=upload.safe_filename,
        content=upload.content,
        magika_client=file_detector,
    )
    # 2. 创建 INIT 行，拿到 doc_id 后才能生成对象存储 key。
    document = await document_repository.create_init_document(
        doc_title=upload.doc_title,
        upload_user=upload.upload_user,
        accessible_by=upload.accessible_by,
    )

    object_key = original_object_key(
        doc_id=document.doc_id,
        safe_filename=upload.safe_filename,
    )
    try:
        # 3. 上传原文；外部对象存储调用不包在数据库事务里。
        await storage.ensure_bucket()
        doc_url = await storage.upload_bytes(
            object_key=object_key,
            content=upload.content,
            content_type="application/octet-stream",
        )
    except Exception as exc:
        raise DocumentStorageFailed() from exc

    # 4. 原文上传成功后推进生命周期并保存稳定 URL。
    await document_repository.mark_uploaded(doc_id=document.doc_id, doc_url=doc_url)

    # 5. 纯文本无需 MinerU 转换，直接发布为 CONVERTED。
    if file_type == DocumentFileType.PLAIN_TEXT:
        await document_repository.mark_converted(
            doc_id=document.doc_id,
            converted_doc_url=doc_url,
            expected_status=DocumentStatus.UPLOADED,
        )
        return DocumentMetadata(
            doc_id=document.doc_id,
            doc_title=upload.doc_title,
            upload_user=upload.upload_user,
            accessible_by=upload.accessible_by,
            doc_url=doc_url,
            converted_doc_url=doc_url,
            status=DocumentStatus.CONVERTED.value,
        )

    # 6. PDF 先进入 CONVERTING，再调用 MinerU 同步转换。
    await document_repository.start_converting(doc_id=document.doc_id)
    try:
        converted_doc_url = await convert_pdf_document(
            doc_id=document.doc_id,
            upload=upload,
            storage=storage,
            mineru_client=mineru_client,
        )
    except DocumentConversionFailed:
        try:
            # 转换失败后回滚到 UPLOADED，保留已上传原文 URL。
            await document_repository.rollback_to_uploaded(doc_id=document.doc_id)
        except Exception as exc:
            raise DocumentStateRollbackFailed() from exc
        raise
    # 7. 只有全部转换产物上传成功后，才发布 converted_doc_url。
    await document_repository.mark_converted(
        doc_id=document.doc_id,
        converted_doc_url=converted_doc_url,
        expected_status=DocumentStatus.CONVERTING,
    )
    return DocumentMetadata(
        doc_id=document.doc_id,
        doc_title=upload.doc_title,
        upload_user=upload.upload_user,
        accessible_by=upload.accessible_by,
        doc_url=doc_url,
        converted_doc_url=converted_doc_url,
        status=DocumentStatus.CONVERTED.value,
    )
