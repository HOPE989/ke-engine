"""Add document vector storage lifecycle status.

Revision ID: 202607060001
Revises: 202607010001
"""

from alembic import op
import sqlalchemy as sa

revision = "202607060001"
down_revision = "202607010001"
branch_labels = None
depends_on = None


DOCUMENT_STATUS_CONSTRAINT = (
    "status IN ('INIT', 'UPLOADED', 'CONVERTING', 'CONVERTED', 'CHUNKED', 'VECTOR_STORED')"
)
OLD_DOCUMENT_STATUS_CONSTRAINT = (
    "status IN ('INIT', 'UPLOADED', 'CONVERTING', 'CONVERTED', 'CHUNKED')"
)


def upgrade() -> None:
    """Extend document lifecycle and segment post-chunking default."""

    op.drop_constraint(
        "ck_knowledge_document_status",
        "knowledge_document",
        type_="check",
    )
    op.create_check_constraint(
        "ck_knowledge_document_status",
        "knowledge_document",
        DOCUMENT_STATUS_CONSTRAINT,
    )
    op.alter_column(
        "knowledge_segment",
        "status",
        existing_type=sa.String(length=255),
        server_default=sa.text("'STORED'"),
        existing_nullable=False,
    )
    op.execute("UPDATE knowledge_segment SET status = 'STORED' WHERE status = 'INIT'")


def downgrade() -> None:
    """Restore pre-vector-storage lifecycle defaults."""

    op.execute("UPDATE knowledge_segment SET status = 'INIT' WHERE status = 'STORED'")
    op.alter_column(
        "knowledge_segment",
        "status",
        existing_type=sa.String(length=255),
        server_default=sa.text("'INIT'"),
        existing_nullable=False,
    )
    op.drop_constraint(
        "ck_knowledge_document_status",
        "knowledge_document",
        type_="check",
    )
    op.create_check_constraint(
        "ck_knowledge_document_status",
        "knowledge_document",
        OLD_DOCUMENT_STATUS_CONSTRAINT,
    )
