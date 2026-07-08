"""Add DATA_QUERY spreadsheet ingestion metadata.

Revision ID: 202607080001
Revises: 202607070001
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "202607080001"
down_revision = "202607070001"
branch_labels = None
depends_on = None


DOCUMENT_STATUS_CONSTRAINT = (
    "status IN ('INIT', 'UPLOADED', 'CONVERTING', 'CONVERTED', "
    "'CHUNKED', 'VECTOR_STORED', 'STORED')"
)
OLD_DOCUMENT_STATUS_CONSTRAINT = (
    "status IN ('INIT', 'UPLOADED', 'CONVERTING', 'CONVERTED', 'CHUNKED', 'VECTOR_STORED')"
)


def upgrade() -> None:
    """Add document options and DATA_QUERY table metadata."""

    table_meta_id = sa.Column("id", sa.BigInteger(), primary_key=True, nullable=False)
    table_meta_namespace = sa.Column("namespace", sa.String(length=255), nullable=False)
    table_meta_document_id = sa.Column(
        "document_id",
        sa.BigInteger(),
        sa.ForeignKey("knowledge_document.doc_id"),
        nullable=False,
    )
    table_meta_table_name = sa.Column("table_name", sa.String(length=255), nullable=False)
    table_meta_description = sa.Column("description", sa.Text(), nullable=False)
    table_meta_create_sql = sa.Column("create_sql", sa.Text(), nullable=True)
    table_meta_columns_info = sa.Column("columns_info", postgresql.JSONB(), nullable=True)
    table_meta_created_at = sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    table_meta_updated_at = sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )

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
    op.add_column(
        "knowledge_document",
        sa.Column(
            "extension",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_table(
        "table_meta",
        table_meta_id,
        table_meta_namespace,
        table_meta_document_id,
        table_meta_table_name,
        table_meta_description,
        table_meta_create_sql,
        table_meta_columns_info,
        table_meta_created_at,
        table_meta_updated_at,
        sa.UniqueConstraint(
            table_meta_namespace,
            table_meta_table_name,
            name="uq_table_meta_namespace_table_name",
        ),
        sa.UniqueConstraint(table_meta_document_id, name="uq_table_meta_document_id"),
    )
    op.create_index("ix_table_meta_namespace", "table_meta", ["namespace"])
    op.create_index("ix_table_meta_document_id", "table_meta", ["document_id"])


def downgrade() -> None:
    """Remove DATA_QUERY table metadata."""

    op.drop_index("ix_table_meta_document_id", table_name="table_meta")
    op.drop_index("ix_table_meta_namespace", table_name="table_meta")
    op.drop_table("table_meta")
    op.drop_column("knowledge_document", "extension")
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
