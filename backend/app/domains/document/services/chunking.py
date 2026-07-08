"""文档切分工作流。"""

from typing import Any

from app.contracts.document.http import DocumentChunkResponse
from app.domains.document.components.segment_builder import build_segment_drafts
from app.domains.document.components.splitters import run_with_document_chunk_lock
from app.domains.document.shared.errors import (
    ChunkPersistenceFailed,
    ChunkSplittingFailed,
    ConvertedMarkdownInvalid,
    ConvertedMarkdownUnavailable,
    DocumentNotFound,
    DocumentStateConflict,
)
from app.domains.document.shared.models import DocumentStatus


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
    """执行单个已转换文档的手动切分工作流。"""

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
