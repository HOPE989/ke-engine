"""文档上传与转换的应用工作流编排。"""

import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.modules.document.errors import (
    ChunkPersistenceFailed,
    ChunkSplittingFailed,
    ConvertedMarkdownInvalid,
    ConvertedMarkdownUnavailable,
    DataQueryUploadBusy,
    DataQueryUploadLockUnavailable,
    DocumentConversionFailed,
    DocumentNotFound,
    DocumentStateConflict,
    DocumentStorageFailed,
    DocumentVectorStorageDispatchFailed,
    UnsupportedDocumentFileType,
)
from app.modules.document.chunking import (
    build_segment_drafts,
    run_with_document_chunk_lock,
)
from app.modules.document.file_types import detect_document_file_type
from app.modules.document.file_types import DocumentFileType
from app.modules.document.markdown import (
    IMAGE_PARSE_ERROR_DESCRIPTION,
    IMAGE_SUFFIXES,
    MARKDOWN_SUFFIXES,
    extract_mineru_zip,
    image_content_type,
    rewrite_markdown_image_links,
    select_markdown_path,
)
from app.modules.document.models import DocumentStatus, KnowledgeBaseType
from app.modules.document.schemas import DocumentChunkResponse, DocumentMetadata
from app.modules.document.storage import (
    asset_object_key,
    converted_markdown_object_key,
    original_object_key,
)

logger = logging.getLogger(__name__)


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
        # 1. 请求 MinerU 产出 ZIP，后续所有解析都基于这个归档。
        zip_bytes = await mineru_client.request_zip(
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
            ensure_image_describer_configured = getattr(
                image_describer,
                "ensure_configured",
                None,
            )
            if ensure_image_describer_configured is not None:
                ensure_image_describer_configured()

            # 3. 先处理 ZIP 里的图片文件，生成后续 Markdown 重写需要的两张表：
            #    - image_urls: Markdown target -> 上传后的 MinIO URL
            #    - image_descriptions: Markdown target -> 模型生成描述或失败占位
            #
            # 每张图都会写入两种 key：ZIP 内相对路径和 basename。这样 MinerU Markdown
            # 无论引用 `images/page-1.png` 还是 `page-1.png`，重写时都能找到同一结果。
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
                    # 单张图片失败不影响主 Markdown 转换。该图片不会进入 image_urls，
                    # rewrite_markdown_image_links 会在看到对应 Markdown 引用时保留原 target，
                    # 并把 alt 写成 `图片解析错误`。
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
                    # 描述结果和 URL 使用同一套 lookup key。这样 URL 能命中哪种 Markdown
                    # target 形式，alt 文案也能按同样形式命中。
                    image_descriptions[image_path.as_posix()] = alt_text
                    image_descriptions[image_path.name] = alt_text

            # 4. 最终 Markdown 重写只依赖上面两张表：
            #    - 外链：保留原 URL 和原 alt
            #    - 本地图片有 URL：改成 MinIO URL，并使用描述或失败占位
            #    - 本地图片无 URL：保留原 target，并使用失败占位
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
    """预留 DATA_QUERY 表元数据并保存原始 spreadsheet 文件。

    该函数运行在 `data_query_upload:{namespace}` 锁内。它只完成上传阶段职责：
    1. 创建 INIT 文档和 table_meta 占位；
    2. 上传原始文件到对象存储；
    3. 将文档推进到 UPLOADED；
    4. 派发异步 worker 导入动态表。

    真正的建表和数据导入不在 HTTP 请求线程执行，而由 worker 在后续事务中完成。
    """

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
    """以非等待方式持有 DATA_QUERY namespace 上传锁并执行操作。

    锁只覆盖上传占位和 override 清理阶段，不覆盖 worker 导入阶段。拿不到锁时直接返回
    busy，避免同一 namespace 下两个 DATA_QUERY 上传同时抢占或覆盖 tableName。
    """

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


async def chunk_document(
    *,
    doc_id: int,
    document_repository: Any,
    storage: Any,
    id_generator: Any,
    lock: Any,
    chunk_size: int,
    overlap: int,
    splitter_factory: Any,
    embed_store_dispatcher: Any | None = None,
) -> Any:
    """执行单个已转换文档的手动切分工作流。

    切分流程只负责按文件类型把 converted 文档拆成数据库 segment，并把文档推进到 `CHUNKED`。
    文件内容加载不在 workflow 里做，而是下沉到具体 splitter：
    Markdown splitter 读取 UTF-8 文本，Excel/CSV splitter 读取 origin bytes。

    当 `embed_store_dispatcher` 存在时，成功持久化后再派发向量存储事件；派发发生在
    `complete_chunking` 返回之后，避免 chunk 持久化失败时产生无法处理的向量存储消息。
    """

    async def operation() -> DocumentChunkResponse:
        document = await document_repository.get_document(doc_id)
        if document is None:
            raise DocumentNotFound()
        if document.status == DocumentStatus.CHUNKED.value:
            segment_count = await document_repository.count_embeddable_segments(doc_id=doc_id)
            return DocumentChunkResponse(
                doc_id=str(doc_id),
                status=DocumentStatus.CHUNKED.value,
                segment_count=segment_count,
            )
        if document.status != DocumentStatus.CONVERTED.value:
            raise DocumentStateConflict()
        if not document.converted_doc_url:
            raise DocumentStateConflict()

        try:
            # 1. 按 file_type 选择唯一 splitter；workflow 不再提前下载 converted 文档。
            splitter = splitter_factory.splitter_for(
                document.file_type,
                chunk_size=chunk_size,
                overlap=overlap,
            )
            # 2. splitter 自己解释 converted_doc_url：Markdown 读文本，Excel/CSV 读 bytes。
            split_chunks = await splitter.split_chunks(
                document=document,
                storage=storage,
                id_generator=id_generator,
            )
        except (DocumentStateConflict, ConvertedMarkdownUnavailable, ConvertedMarkdownInvalid):
            raise
        except Exception as exc:
            raise ChunkSplittingFailed() from exc

        # 3. 统一把 splitter 输出转换成 knowledge_segment 待写入草稿。
        segment_drafts = build_segment_drafts(
            document=document,
            split_chunks=split_chunks,
            id_generator=id_generator,
        )
        try:
            await document_repository.complete_chunking(
                doc_id=doc_id,
                segment_drafts=segment_drafts,
            )
        except ChunkPersistenceFailed:
            raise
        except Exception as exc:
            raise ChunkPersistenceFailed() from exc
        # 只有 segment 和文档状态已经成功落库后，才触发下一阶段向量存储。
        if embed_store_dispatcher is not None:
            await embed_store_dispatcher.dispatch(doc_id)
        return DocumentChunkResponse(
            doc_id=str(doc_id),
            status=DocumentStatus.CHUNKED.value,
            segment_count=len(segment_drafts),
        )

    return await run_with_document_chunk_lock(lock=lock, operation=operation)


async def request_document_vector_storage(
    *,
    doc_id: int,
    document_repository: Any,
    embed_store_dispatcher: Any,
) -> None:
    """校验文档状态并手动派发向量存储事件。

    该函数服务于手动 API 触发：它不会调用 embedding model，也不会写 Elasticsearch。
    它只负责判断文档是否存在、是否已经完成、是否处于可处理的 `CHUNKED` 状态，然后派发
    与自动 chunk-success path 相同的 Kafka 事件。
    """

    # 1. 找不到文档时，不派发 Kafka，交由 router 映射为 404。
    document = await document_repository.get_document(doc_id)
    if document is None:
        raise DocumentNotFound()
    # 2. 已完成文档保持幂等成功，不重复派发向量存储事件。
    if document.status == DocumentStatus.VECTOR_STORED.value:
        return
    # 3. 只有 CHUNKED 文档允许进入向量存储阶段。
    if document.status != DocumentStatus.CHUNKED.value:
        raise DocumentStateConflict()

    try:
        # 4. 手动入口和自动入口共用同一事件类型，避免两套 worker 逻辑。
        await embed_store_dispatcher.dispatch(doc_id)
    except Exception as exc:
        raise DocumentVectorStorageDispatchFailed() from exc
