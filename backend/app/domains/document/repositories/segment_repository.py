"""knowledge_segment 仓储入口。"""

from collections.abc import Sequence

from sqlalchemy import select, tuple_

from app.domains.document.repositories.document_repository import DocumentRepository
from app.domains.document.shared.models import KnowledgeSegment


class SegmentRepository(DocumentRepository):
    """Segment 仓储视图。

    当前复用 `DocumentRepository` 的 session 与既有方法；后续可以逐步把 segment
    专属方法物理移动到这里。
    """

    async def get_parent_texts(
        self,
        references: Sequence[tuple[str, str]],
    ) -> dict[tuple[str, str], str]:
        """按 ``(docId, parentChunkId)`` 批量读取已存储父分段正文。"""

        normalized = {
            (int(doc_id.strip()), parent_chunk_id.strip())
            for doc_id, parent_chunk_id in references
            if doc_id.strip() and parent_chunk_id.strip()
        }
        if not normalized:
            return {}

        async with self._session_factory() as session:
            result = await session.execute(
                select(
                    KnowledgeSegment.document_id,
                    KnowledgeSegment.chunk_id,
                    KnowledgeSegment.text,
                ).where(
                    tuple_(
                        KnowledgeSegment.document_id,
                        KnowledgeSegment.chunk_id,
                    ).in_(normalized),
                    KnowledgeSegment.status == "STORED",
                    KnowledgeSegment.skip_embedding.is_(True),
                )
            )

        return {
            (str(document_id), chunk_id): text
            for document_id, chunk_id, text in result.all()
        }
