"""knowledge_document 的持久化 repository。"""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.document.errors import DocumentStateConflict
from app.modules.document.models import DocumentStatus, KnowledgeDocument


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
