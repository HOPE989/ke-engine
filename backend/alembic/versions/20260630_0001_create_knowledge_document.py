"""create knowledge document table

Revision ID: 20260630_0001
Revises:
Create Date: 2026-06-30 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "20260630_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_document",
        sa.Column("doc_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("doc_title", sa.String(length=1024), nullable=False),
        sa.Column("upload_user", sa.String(length=255), nullable=False),
        sa.Column("doc_url", sa.String(length=2048), nullable=True),
        sa.Column("converted_doc_url", sa.String(length=2048), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'INIT'"),
            nullable=False,
        ),
        sa.Column("accessible_by", sa.String(length=1024), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('INIT', 'UPLOADED', 'CONVERTING', 'CONVERTED')",
            name="ck_knowledge_document_status",
        ),
    )
    op.create_index("ix_knowledge_document_status", "knowledge_document", ["status"])
    op.create_index(
        "ix_knowledge_document_upload_user",
        "knowledge_document",
        ["upload_user"],
    )
    op.create_index(
        "ix_knowledge_document_created_at",
        "knowledge_document",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_document_created_at", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_upload_user", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_status", table_name="knowledge_document")
    op.drop_table("knowledge_document")
