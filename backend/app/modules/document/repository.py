"""knowledge_document 的持久化 repository。"""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.document.errors import (
    ChunkPersistenceFailed,
    DocumentStateConflict,
)
from app.modules.document.models import DocumentStatus, KnowledgeDocument, KnowledgeSegment


def _status_value(status: DocumentStatus | str) -> str:
    """把状态枚举或字符串统一转换为数据库存储值。"""

    if isinstance(status, DocumentStatus):
        return status.value
    return status


async def _execute_update_with_expected_status(
    session: AsyncSession,
    *,
    doc_id: int,
    expected_status: DocumentStatus | str,
    values: dict[str, str],
) -> None:
    """执行带 expected-status 条件的生命周期更新。"""

    # WHERE 同时约束 doc_id 和当前状态，实现轻量并发保护。
    statement = (
        update(KnowledgeDocument)
        .where(
            KnowledgeDocument.doc_id == doc_id,
            KnowledgeDocument.status == _status_value(expected_status),
        )
        .values(**values, updated_at=func.now())
    )
    result = await session.execute(statement)
    if result.rowcount == 0:
        raise DocumentStateConflict()
    # 状态更新单独提交，避免跨 MinIO/MinerU 外部调用持有事务。
    await session.commit()


class DocumentRepository:
    """使用 session_factory 管理短生命周期数据库会话的文档 repository。"""

    def __init__(self, session_factory) -> None:
        """保存启动期创建的 session_factory。"""

        self._session_factory = session_factory

    async def create_init_document(
        self,
        *,
        doc_id: int,
        doc_title: str,
        upload_user: str,
        accessible_by: str,
        file_type: str,
    ) -> KnowledgeDocument:
        """创建并提交 INIT 状态的文档行，返回带 doc_id 的模型。"""

        document = KnowledgeDocument(
            doc_id=doc_id,
            doc_title=doc_title,
            upload_user=upload_user,
            accessible_by=accessible_by,
            file_type=file_type,
            status=DocumentStatus.INIT.value,
        )
        async with self._session_factory() as session:
            session.add(document)
            await session.commit()
        return document

    async def get_document(self, doc_id: int) -> KnowledgeDocument | None:
        """按 doc_id 读取文档元数据，找不到时返回 None。"""

        async with self._session_factory() as session:
            result = await session.execute(
                select(KnowledgeDocument).where(KnowledgeDocument.doc_id == doc_id)
            )
            return result.scalar_one_or_none()

    async def count_embeddable_segments(self, *, doc_id: int) -> int:
        """统计指定文档需要 embedding 的分段数量。"""

        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count())
                .select_from(KnowledgeSegment)
                .where(
                    KnowledgeSegment.document_id == doc_id,
                    KnowledgeSegment.skip_embedding.is_(False),
                )
            )
            return int(result.scalar_one())

    async def list_pending_embeddable_segments(
        self,
        *,
        session: AsyncSession,
        doc_id: int,
        limit: int = 100,
    ) -> list[KnowledgeSegment]:
        """在已有事务中按固定第一页读取待向量化分段。"""

        result = await session.execute(
            select(KnowledgeSegment)
            .where(
                KnowledgeSegment.document_id == doc_id,
                KnowledgeSegment.status == "STORED",
                KnowledgeSegment.skip_embedding.is_(False),
                KnowledgeSegment.embedding_id.is_(None),
            )
            .order_by(KnowledgeSegment.chunk_order.asc(), KnowledgeSegment.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_segments_vector_stored(
        self,
        *,
        session: AsyncSession,
        segment_embedding_ids: dict[int, str],
    ) -> None:
        """在已有事务中写回分段 vector ID 并推进分段状态。"""

        for segment_id, embedding_id in segment_embedding_ids.items():
            result = await session.execute(
                update(KnowledgeSegment)
                .where(KnowledgeSegment.id == segment_id)
                .values(
                    embedding_id=embedding_id,
                    status=DocumentStatus.VECTOR_STORED.value,
                )
            )
            if result.rowcount != 1:
                raise DocumentStateConflict()

    async def count_pending_embeddable_segments(
        self,
        *,
        session: AsyncSession,
        doc_id: int,
    ) -> int:
        """在已有事务中 double-check 仍待向量化的分段数。"""

        result = await session.execute(
            select(func.count())
            .select_from(KnowledgeSegment)
            .where(
                KnowledgeSegment.document_id == doc_id,
                KnowledgeSegment.status == "STORED",
                KnowledgeSegment.skip_embedding.is_(False),
                KnowledgeSegment.embedding_id.is_(None),
            )
        )
        return int(result.scalar_one())

    async def mark_document_vector_stored(
        self,
        *,
        session: AsyncSession,
        doc_id: int,
    ) -> None:
        """在已有事务中将 CHUNKED 文档推进到 VECTOR_STORED。"""

        result = await session.execute(
            update(KnowledgeDocument)
            .where(
                KnowledgeDocument.doc_id == doc_id,
                KnowledgeDocument.status == DocumentStatus.CHUNKED.value,
            )
            .values(status=DocumentStatus.VECTOR_STORED.value, updated_at=func.now())
        )
        if result.rowcount != 1:
            raise DocumentStateConflict()

    async def _update_with_expected_status(
        self,
        *,
        doc_id: int,
        expected_status: DocumentStatus | str,
        values: dict[str, str],
    ) -> None:
        """用短 session 执行带 expected-status 条件的生命周期更新。"""

        async with self._session_factory() as session:
            await _execute_update_with_expected_status(
                session,
                doc_id=doc_id,
                expected_status=expected_status,
                values=values,
            )

    async def mark_uploaded(
        self,
        *,
        doc_id: int,
        doc_url: str,
    ) -> None:
        """记录原文 URL，并将 INIT 文档推进到 UPLOADED。"""

        await self._update_with_expected_status(
            doc_id=doc_id,
            expected_status=DocumentStatus.INIT,
            values={
                "doc_url": doc_url,
                "status": DocumentStatus.UPLOADED.value,
            },
        )

    async def start_converting(self, *, doc_id: int) -> None:
        """将 UPLOADED 文档推进到 CONVERTING。"""

        await self._update_with_expected_status(
            doc_id=doc_id,
            expected_status=DocumentStatus.UPLOADED,
            values={"status": DocumentStatus.CONVERTING.value},
        )

    async def mark_converted(
        self,
        *,
        doc_id: int,
        converted_doc_url: str,
        expected_status: DocumentStatus | str,
    ) -> None:
        """记录转换后 URL，并将文档推进到 CONVERTED。"""

        await self._update_with_expected_status(
            doc_id=doc_id,
            expected_status=expected_status,
            values={
                "converted_doc_url": converted_doc_url,
                "status": DocumentStatus.CONVERTED.value,
            },
        )

    async def rollback_to_uploaded(self, *, doc_id: int) -> None:
        """PDF 转换失败后将 CONVERTING 文档回滚到 UPLOADED。"""

        await self._update_with_expected_status(
            doc_id=doc_id,
            expected_status=DocumentStatus.CONVERTING,
            values={"status": DocumentStatus.UPLOADED.value},
        )

    async def complete_chunking(self, *, doc_id: int, segment_drafts: list) -> None:
        """在一个事务中写入 segment 并将 CONVERTED 文档推进到 CHUNKED。"""

        async with self._session_factory() as session:
            try:
                async with session.begin():
                    session.add_all(
                        [
                            KnowledgeSegment(
                                id=draft.id,
                                chunk_id=draft.chunk_id,
                                text=draft.text,
                                document_id=draft.document_id,
                                chunk_order=draft.chunk_order,
                                embedding_id=draft.embedding_id,
                                status=draft.status,
                                metadata_=draft.metadata,
                                skip_embedding=draft.skip_embedding,
                            )
                            for draft in segment_drafts
                        ]
                    )
                    statement = (
                        update(KnowledgeDocument)
                        .where(
                            KnowledgeDocument.doc_id == doc_id,
                            KnowledgeDocument.status == DocumentStatus.CONVERTED.value,
                        )
                        .values(status=DocumentStatus.CHUNKED.value, updated_at=func.now())
                    )
                    result = await session.execute(statement)
                    if result.rowcount == 0:
                        raise ChunkPersistenceFailed()
            except ChunkPersistenceFailed:
                raise
            except Exception as exc:
                raise ChunkPersistenceFailed() from exc
