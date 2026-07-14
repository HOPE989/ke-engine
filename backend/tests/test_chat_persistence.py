import importlib
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _chat_models():
    from app.domains.chat.shared.models import (
        Conversation,
        ConversationStatus,
        Message,
        MessageRole,
    )

    return ConversationStatus, MessageRole, Conversation, Message


def _constraint(table, constraint_type, name):
    return next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, constraint_type) and constraint.name == name
    )


def _index_expressions(index):
    return tuple(str(expression) for expression in index.expressions)


def test_chat_persistence_enums_define_only_supported_values():
    ConversationStatus, MessageRole, _, _ = _chat_models()

    assert [status.value for status in ConversationStatus] == [
        "ACTIVE",
        "ARCHIVED",
        "DELETED",
    ]
    assert [role.value for role in MessageRole] == ["USER", "ASSISTANT"]


def test_conversation_model_defines_exact_columns_and_defaults():
    ConversationStatus, _, Conversation, _ = _chat_models()
    table = Conversation.__table__

    assert table.name == "conversations"
    assert tuple(table.columns.keys()) == (
        "id",
        "user_id",
        "title",
        "status",
        "created_at",
        "updated_at",
    )

    assert isinstance(table.c.id.type, sa.BigInteger)
    assert table.c.id.primary_key is True
    assert table.c.id.identity is None
    assert table.c.id.server_default is None

    assert isinstance(table.c.user_id.type, sa.String)
    assert table.c.user_id.type.length == 255
    assert table.c.user_id.nullable is False
    assert isinstance(table.c.title.type, sa.String)
    assert table.c.title.type.length == 255
    assert table.c.title.nullable is False

    assert isinstance(table.c.status.type, sa.String)
    assert table.c.status.type.length == 32
    assert table.c.status.nullable is False
    assert table.c.status.default.arg == ConversationStatus.ACTIVE.value
    assert str(table.c.status.server_default.arg) == "ACTIVE"

    for column in (table.c.created_at, table.c.updated_at):
        assert isinstance(column.type, sa.DateTime)
        assert column.type.timezone is True
        assert column.nullable is False
        assert column.server_default is not None
    assert table.c.updated_at.onupdate is not None


def test_conversation_model_defines_status_constraint_and_listing_index():
    _, _, Conversation, _ = _chat_models()
    table = Conversation.__table__

    status_constraint = _constraint(
        table,
        sa.CheckConstraint,
        "ck_conversations_status",
    )
    constraint_sql = str(status_constraint.sqltext)
    for status in ("ACTIVE", "ARCHIVED", "DELETED"):
        assert status in constraint_sql

    listing_index = next(
        index
        for index in table.indexes
        if index.name == "ix_conversations_user_status_updated_id"
    )
    assert _index_expressions(listing_index) == (
        "conversations.user_id",
        "conversations.status",
        "updated_at DESC",
        "id DESC",
    )


def test_message_model_defines_exact_columns_and_json_defaults():
    _, _, _, Message = _chat_models()
    table = Message.__table__

    assert table.name == "messages"
    assert tuple(table.columns.keys()) == (
        "id",
        "conversation_id",
        "parent_message_id",
        "role",
        "content",
        "transformed_content",
        "token_count",
        "model_name",
        "rag_references",
        "metadata",
        "created_at",
        "updated_at",
    )
    assert "status" not in table.c

    assert isinstance(table.c.id.type, sa.BigInteger)
    assert table.c.id.primary_key is True
    assert table.c.id.identity is None
    assert table.c.id.server_default is None
    assert isinstance(table.c.conversation_id.type, sa.BigInteger)
    assert table.c.conversation_id.nullable is False
    assert isinstance(table.c.parent_message_id.type, sa.BigInteger)
    assert table.c.parent_message_id.nullable is True
    assert isinstance(table.c.role.type, sa.String)
    assert table.c.role.type.length == 32
    assert table.c.role.nullable is False
    assert isinstance(table.c.content.type, sa.Text)
    assert table.c.content.nullable is False
    assert isinstance(table.c.transformed_content.type, sa.Text)
    assert table.c.transformed_content.nullable is True
    assert isinstance(table.c.token_count.type, sa.Integer)
    assert table.c.token_count.nullable is True
    assert isinstance(table.c.model_name.type, sa.String)
    assert table.c.model_name.type.length == 255
    assert table.c.model_name.nullable is True

    assert isinstance(table.c.rag_references.type, postgresql.JSONB)
    assert table.c.rag_references.nullable is False
    assert table.c.rag_references.default.arg(None) == []
    assert str(table.c.rag_references.server_default.arg) == "'[]'::jsonb"
    assert isinstance(table.c.metadata.type, postgresql.JSONB)
    assert table.c.metadata.nullable is False
    assert table.c.metadata.default.arg(None) == {}
    assert str(table.c.metadata.server_default.arg) == "'{}'::jsonb"

    for column in (table.c.created_at, table.c.updated_at):
        assert isinstance(column.type, sa.DateTime)
        assert column.type.timezone is True
        assert column.nullable is False
        assert column.server_default is not None
    assert table.c.updated_at.onupdate is not None


def test_message_model_maps_metadata_column_to_safe_python_attribute():
    _, _, _, Message = _chat_models()

    assert hasattr(Message, "metadata_")
    assert Message.metadata_.property.columns[0].name == "metadata"


def test_message_model_defines_role_and_same_conversation_parent_constraints():
    _, _, _, Message = _chat_models()
    table = Message.__table__

    role_constraint = _constraint(table, sa.CheckConstraint, "ck_messages_role")
    role_sql = str(role_constraint.sqltext)
    assert "USER" in role_sql
    assert "ASSISTANT" in role_sql
    assert "SYSTEM" not in role_sql
    assert "TOOL" not in role_sql

    unique_constraint = _constraint(
        table,
        sa.UniqueConstraint,
        "uq_messages_conversation_id_id",
    )
    assert tuple(unique_constraint.columns.keys()) == ("conversation_id", "id")

    parent_constraint = _constraint(
        table,
        sa.ForeignKeyConstraint,
        "fk_messages_parent_same_conversation",
    )
    assert tuple(parent_constraint.columns.keys()) == (
        "conversation_id",
        "parent_message_id",
    )
    assert tuple(element.target_fullname for element in parent_constraint.elements) == (
        "messages.conversation_id",
        "messages.id",
    )

    conversation_foreign_keys = [
        foreign_key
        for foreign_key in table.c.conversation_id.foreign_keys
        if foreign_key.target_fullname == "conversations.id"
    ]
    assert len(conversation_foreign_keys) == 1
    assert conversation_foreign_keys[0].ondelete == "CASCADE"


def test_message_model_defines_history_and_parent_indexes():
    _, _, _, Message = _chat_models()
    indexes = {index.name: index for index in Message.__table__.indexes}

    assert _index_expressions(indexes["ix_messages_conversation_created_id"]) == (
        "messages.conversation_id",
        "messages.created_at",
        "messages.id",
    )
    assert _index_expressions(indexes["ix_messages_conversation_parent"]) == (
        "messages.conversation_id",
        "messages.parent_message_id",
    )


def test_alembic_env_loads_chat_models_before_target_metadata():
    env_source = (BACKEND_DIR / "alembic" / "env.py").read_text(encoding="utf-8")
    chat_import = "from app.domains.chat.shared import models as chat_models"

    assert chat_import in env_source
    assert env_source.index(chat_import) < env_source.index("target_metadata = Base.metadata")

    importlib.import_module("app.domains.chat.shared.models")
    from app.infrastructure.db.base import Base

    assert {"conversations", "messages"} <= set(Base.metadata.tables)


@pytest.mark.asyncio
async def test_postgresql_enforces_chat_constraints_defaults_and_cascade():
    database_url = os.environ.get("CHAT_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set CHAT_TEST_DATABASE_URL to run PostgreSQL Chat integration tests")

    ConversationStatus, MessageRole, Conversation, Message = _chat_models()
    schema_name = f"test_chat_{uuid4().hex}"

    bootstrap_engine = create_async_engine(database_url)
    async with bootstrap_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    await bootstrap_engine.dispose()

    engine = create_async_engine(database_url)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_search_path(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f'SET search_path TO "{schema_name}"')
        finally:
            cursor.close()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Conversation.__table__.create)
            await connection.run_sync(Message.__table__.create)

        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with session_factory.begin() as session:
            await session.execute(
                text(
                    "INSERT INTO conversations (id, user_id, title) "
                    "VALUES (1001, 'user-1', 'First chat')"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO conversations (id, user_id, title) "
                    "VALUES (1002, 'user-1', 'Second chat')"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO messages (id, conversation_id, role, content) "
                    "VALUES (2001, 1001, 'USER', 'question')"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO messages "
                    "(id, conversation_id, parent_message_id, role, content) "
                    "VALUES (2002, 1001, 2001, 'ASSISTANT', 'answer')"
                )
            )

        async with session_factory() as session:
            status = await session.scalar(
                sa.select(Conversation.status).where(Conversation.id == 1001)
            )
            rag_references, metadata = (
                await session.execute(
                    sa.select(Message.rag_references, Message.metadata_).where(
                        Message.id == 2001
                    )
                )
            ).one()
        assert status == ConversationStatus.ACTIVE.value
        assert rag_references == []
        assert metadata == {}

        with pytest.raises(IntegrityError):
            async with session_factory.begin() as session:
                await session.execute(
                    sa.insert(Message).values(
                        id=2003,
                        conversation_id=1002,
                        parent_message_id=2001,
                        role=MessageRole.USER.value,
                        content="cross-conversation child",
                    )
                )

        with pytest.raises(IntegrityError):
            async with session_factory.begin() as session:
                await session.execute(
                    sa.insert(Conversation).values(
                        id=1003,
                        user_id="user-1",
                        title="Invalid status",
                        status="UNKNOWN",
                    )
                )

        with pytest.raises(IntegrityError):
            async with session_factory.begin() as session:
                await session.execute(
                    sa.insert(Message).values(
                        id=2004,
                        conversation_id=1002,
                        role="SYSTEM",
                        content="runtime-only message",
                    )
                )

        async with session_factory.begin() as session:
            await session.execute(sa.delete(Conversation).where(Conversation.id == 1001))

        async with session_factory() as session:
            remaining_messages = await session.scalar(
                sa.select(sa.func.count())
                .select_from(Message)
                .where(Message.conversation_id == 1001)
            )
        assert remaining_messages == 0
    finally:
        await engine.dispose()
        cleanup_engine = create_async_engine(database_url)
        async with cleanup_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        await cleanup_engine.dispose()
