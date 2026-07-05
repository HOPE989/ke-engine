"""Add document vector storage lifecycle status.

本迁移把文档生命周期扩展到向量存储阶段，并把新切分 segment 的默认状态从 `INIT`
调整为 `STORED`。这样 chunking 完成后，segment 表示“已存入关系库”，后续 worker 再把
可 embedding 的 segment 推进到 `VECTOR_STORED`。

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
    """扩展文档状态约束，并把已有 INIT segment 迁移为 STORED。"""

    # 1. PostgreSQL check constraint 不能直接追加枚举值，先删旧约束再建新约束。
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
    # 2. 新 segment 默认进入 STORED，表示已经完成关系库持久化。
    op.alter_column(
        "knowledge_segment",
        "status",
        existing_type=sa.String(length=255),
        server_default=sa.text("'STORED'"),
        existing_nullable=False,
    )
    # 3. 兼容已有本地数据：历史 INIT segment 在新语义下等价于 STORED。
    op.execute("UPDATE knowledge_segment SET status = 'STORED' WHERE status = 'INIT'")


def downgrade() -> None:
    """恢复向量存储变更前的状态约束和 segment 默认值。"""

    # 降级时先把 STORED 回写为旧版本认识的 INIT，再收紧 check/default。
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
