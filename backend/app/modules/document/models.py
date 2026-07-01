"""文档上传的 SQLAlchemy 持久化模型。"""

from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentStatus(str, Enum):
    """knowledge_document.status 允许的生命周期状态。"""

    INIT = "INIT"
    UPLOADED = "UPLOADED"
    CONVERTING = "CONVERTING"
    CONVERTED = "CONVERTED"


class KnowledgeDocument(Base):
    """knowledge_document 表的 ORM 映射。"""

    __tablename__ = "knowledge_document"
    __table_args__ = (
        CheckConstraint(
            "status IN ('INIT', 'UPLOADED', 'CONVERTING', 'CONVERTED')",
            name="ck_knowledge_document_status",
        ),
    )

    doc_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    doc_title: Mapped[str] = mapped_column(String(1024), nullable=False)
    upload_user: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    doc_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    converted_doc_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DocumentStatus.INIT.value,
        server_default=DocumentStatus.INIT.value,
        index=True,
    )
    accessible_by: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
