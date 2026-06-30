from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.modules.document.constants import DocumentStatus


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_document"

    doc_id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    doc_title: Mapped[str] = mapped_column(sa.String(1024), nullable=False)
    upload_user: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    doc_url: Mapped[str | None] = mapped_column(sa.String(2048), nullable=True)
    converted_doc_url: Mapped[str | None] = mapped_column(sa.String(2048), nullable=True)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default=sa.text("'INIT'"),
        default=DocumentStatus.INIT,
    )
    accessible_by: Mapped[str] = mapped_column(sa.String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    @classmethod
    def create(
        cls,
        *,
        doc_title: str,
        upload_user: str,
        accessible_by: str,
    ) -> "KnowledgeDocument":
        return cls(
            doc_title=doc_title,
            upload_user=upload_user,
            accessible_by=accessible_by,
            status=DocumentStatus.INIT,
        )

    def mark_uploaded(self, doc_url: str) -> None:
        self.doc_url = doc_url
        self.status = DocumentStatus.UPLOADED

    def start_converting(self) -> None:
        self.status = DocumentStatus.CONVERTING

    def mark_converted(self, converted_doc_url: str) -> None:
        self.converted_doc_url = converted_doc_url
        self.status = DocumentStatus.CONVERTED

    def rollback_to_uploaded(self) -> None:
        self.converted_doc_url = None
        self.status = DocumentStatus.UPLOADED
