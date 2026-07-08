"""Document 领域仓储。"""

from app.domains.document.repositories.document_repository import DocumentRepository
from app.domains.document.repositories.segment_repository import SegmentRepository
from app.domains.document.repositories.table_repository import TableRepository

__all__ = ["DocumentRepository", "SegmentRepository", "TableRepository"]
