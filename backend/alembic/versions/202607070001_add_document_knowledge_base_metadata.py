"""Add document knowledge base metadata.

Revision ID: 202607070001
Revises: 202607060001
"""

from alembic import op
import sqlalchemy as sa

revision = "202607070001"
down_revision = "202607060001"
branch_labels = None
depends_on = None


KNOWLEDGE_BASE_TYPE_CONSTRAINT = "knowledge_base_type IN ('DOCUMENT_SEARCH', 'DATA_QUERY')"


def upgrade() -> None:
    """Add upload metadata columns for knowledge base routing."""

    op.add_column(
        "knowledge_document",
        sa.Column("description", sa.Text(), nullable=False),
    )
    op.add_column(
        "knowledge_document",
        sa.Column("knowledge_base_type", sa.String(length=64), nullable=False),
    )
    op.create_check_constraint(
        "ck_knowledge_document_knowledge_base_type",
        "knowledge_document",
        KNOWLEDGE_BASE_TYPE_CONSTRAINT,
    )
    op.create_index(
        "ix_knowledge_document_knowledge_base_type",
        "knowledge_document",
        ["knowledge_base_type"],
    )


def downgrade() -> None:
    """Remove upload metadata columns for knowledge base routing."""

    op.drop_index("ix_knowledge_document_knowledge_base_type", table_name="knowledge_document")
    op.drop_constraint(
        "ck_knowledge_document_knowledge_base_type",
        "knowledge_document",
        type_="check",
    )
    op.drop_column("knowledge_document", "knowledge_base_type")
    op.drop_column("knowledge_document", "description")
