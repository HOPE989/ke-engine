"""创建 Chat 会话与消息持久化表。

Revision ID: 202607140001
Revises: 202607080001
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202607140001"
down_revision = "202607080001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建 conversations、messages 及其约束和查询索引。"""

    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
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
            "status IN ('ACTIVE', 'ARCHIVED', 'DELETED')",
            name="ck_conversations_status",
        ),
    )
    op.create_index(
        "ix_conversations_user_status_updated_id",
        "conversations",
        ["user_id", "status", sa.text("updated_at DESC"), sa.text("id DESC")],
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            sa.BigInteger(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_message_id", sa.BigInteger(), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("transformed_content", sa.Text(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column(
            "rag_references",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
            "role IN ('USER', 'ASSISTANT')",
            name="ck_messages_role",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "id",
            name="uq_messages_conversation_id_id",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "parent_message_id"],
            ["messages.conversation_id", "messages.id"],
            name="fk_messages_parent_same_conversation",
        ),
    )
    op.create_index(
        "ix_messages_conversation_created_id",
        "messages",
        ["conversation_id", "created_at", "id"],
    )
    op.create_index(
        "ix_messages_conversation_parent",
        "messages",
        ["conversation_id", "parent_message_id"],
    )


def downgrade() -> None:
    """按依赖逆序删除 Chat 会话与消息持久化表。"""

    op.drop_index("ix_messages_conversation_parent", table_name="messages")
    op.drop_index("ix_messages_conversation_created_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index(
        "ix_conversations_user_status_updated_id",
        table_name="conversations",
    )
    op.drop_table("conversations")
