import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.document.constants import DocumentStatus
from app.modules.document.exceptions import DocumentStateConflictError
from app.modules.document.models import KnowledgeDocument


class KnowledgeDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, document: KnowledgeDocument) -> None:
        self.session.add(document)

    async def get(self, doc_id: int) -> KnowledgeDocument | None:
        return await self.session.get(KnowledgeDocument, doc_id)

    async def mark_uploaded(self, doc_id: int, doc_url: str) -> None:
        await self._guarded_update(
            doc_id,
            expected_status=DocumentStatus.INIT,
            values={
                "doc_url": doc_url,
                "status": DocumentStatus.UPLOADED,
            },
        )

    async def start_converting(self, doc_id: int) -> None:
        await self._guarded_update(
            doc_id,
            expected_status=DocumentStatus.UPLOADED,
            values={"status": DocumentStatus.CONVERTING},
        )

    async def mark_converted(self, doc_id: int, converted_doc_url: str) -> None:
        await self._guarded_update(
            doc_id,
            expected_status=DocumentStatus.CONVERTING,
            values={
                "converted_doc_url": converted_doc_url,
                "status": DocumentStatus.CONVERTED,
            },
        )

    async def rollback_to_uploaded(self, doc_id: int) -> None:
        await self._guarded_update(
            doc_id,
            expected_status=DocumentStatus.CONVERTING,
            values={
                "converted_doc_url": None,
                "status": DocumentStatus.UPLOADED,
            },
        )

    async def _guarded_update(
        self,
        doc_id: int,
        *,
        expected_status: DocumentStatus,
        values: dict[str, object],
    ) -> None:
        statement = (
            sa.update(KnowledgeDocument)
            .where(KnowledgeDocument.doc_id == doc_id)
            .where(KnowledgeDocument.status == expected_status)
            .values(**values, updated_at=sa.func.now())
            .execution_options(synchronize_session="fetch")
        )
        result = await self.session.execute(statement)
        if result.rowcount != 1:
            raise DocumentStateConflictError()
