"""文档上传的 SQLAlchemy 持久化模型。"""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentStatus(str, Enum):
    """knowledge_document.status 允许的生命周期状态。"""

    INIT = "INIT"
    UPLOADED = "UPLOADED"
    CONVERTING = "CONVERTING"
    CONVERTED = "CONVERTED"
    CHUNKED = "CHUNKED"
    VECTOR_STORED = "VECTOR_STORED"
    STORED = "STORED"


class KnowledgeBaseType(str, Enum):
    """knowledge_document.knowledge_base_type 允许的知识库来源类型。"""

    DOCUMENT_SEARCH = "DOCUMENT_SEARCH"
    DATA_QUERY = "DATA_QUERY"


KNOWLEDGE_BASE_TYPE_CONSTRAINT = "knowledge_base_type IN ('DOCUMENT_SEARCH', 'DATA_QUERY')"


class KnowledgeDocument(Base):
    """knowledge_document 表的 ORM 映射。"""

    __tablename__ = "knowledge_document"
    __table_args__ = (
        CheckConstraint(
            (
                "status IN ('INIT', 'UPLOADED', 'CONVERTING', 'CONVERTED', "
                "'CHUNKED', 'VECTOR_STORED', 'STORED')"
            ),
            name="ck_knowledge_document_status",
        ),
        CheckConstraint(
            KNOWLEDGE_BASE_TYPE_CONSTRAINT,
            name="ck_knowledge_document_knowledge_base_type",
        ),
    )

    doc_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    doc_title: Mapped[str] = mapped_column(String(1024), nullable=False)
    upload_user: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_base_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    extension: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
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


class KnowledgeSegment(Base):
    """knowledge_segment 表的 ORM 映射。"""

    __tablename__ = "knowledge_segment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_document.doc_id"),
        nullable=False,
        index=True,
    )
    chunk_order: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    embedding_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="STORED",
        server_default="STORED",
        index=True,
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False)
    skip_embedding: Mapped[bool] = mapped_column(Boolean, nullable=False)


class TableMeta(Base):
    """DATA_QUERY spreadsheet generated table metadata."""

    __tablename__ = "table_meta"
    __table_args__ = (
        UniqueConstraint("namespace", "table_name", name="uq_table_meta_namespace_table_name"),
        UniqueConstraint("document_id", name="uq_table_meta_document_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    namespace: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_document.doc_id"),
        nullable=False,
        index=True,
    )
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    create_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    columns_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
