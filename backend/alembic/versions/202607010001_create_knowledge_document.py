"""创建 knowledge_document 表。

Revision ID: 202607010001
Revises: None
"""

from alembic import op
import sqlalchemy as sa

revision = "202607010001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建文档元数据表及查询索引。"""

    op.create_table(
        "knowledge_document",
        sa.Column("doc_id", sa.BigInteger(), sa.Identity(), primary_key=True, nullable=False),
        sa.Column("doc_title", sa.String(length=1024), nullable=False),
        sa.Column("upload_user", sa.String(length=255), nullable=False),
        sa.Column("doc_url", sa.String(length=2048), nullable=True),
        sa.Column("converted_doc_url", sa.String(length=2048), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'INIT'")),
        sa.Column("accessible_by", sa.String(length=1024), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('INIT', 'UPLOADED', 'CONVERTING', 'CONVERTED')",
            name="ck_knowledge_document_status",
        ),
    )
    op.create_index("ix_knowledge_document_status", "knowledge_document", ["status"])
    op.create_index("ix_knowledge_document_upload_user", "knowledge_document", ["upload_user"])
    op.create_index("ix_knowledge_document_created_at", "knowledge_document", ["created_at"])


def downgrade() -> None:
    """删除文档元数据表及其索引。"""

    op.drop_index("ix_knowledge_document_created_at", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_upload_user", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_status", table_name="knowledge_document")
    op.drop_table("knowledge_document")
