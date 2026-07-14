from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects import postgresql

from app.domains.chat.shared.models import Conversation, Message


class FakeScalarResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, *result_pages):
        self.result_pages = list(result_pages)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeScalarResult(self.result_pages.pop(0))


def _sql(statement):
    return str(statement.compile(dialect=postgresql.dialect())).lower()


@pytest.mark.asyncio
async def test_conversations_use_owned_newest_first_keyset_pages_without_duplicates():
    from app.domains.chat.repositories import ConversationCursor, ConversationRepository

    now = datetime(2026, 7, 14, tzinfo=UTC)
    rows = [
        Conversation(id=30, user_id="alice", title="new", updated_at=now),
        Conversation(id=20, user_id="alice", title="middle", updated_at=now),
        Conversation(
            id=10,
            user_id="alice",
            title="old",
            updated_at=now - timedelta(seconds=1),
        ),
    ]
    first_session = FakeSession(rows)
    first_items, next_cursor = await ConversationRepository(first_session).list_owned(
        user_id="alice",
        limit=2,
    )

    assert [item.id for item in first_items] == [30, 20]
    assert ConversationCursor.decode(next_cursor) == ConversationCursor(now, 20)
    first_sql = _sql(first_session.statements[0])
    assert "conversations.user_id" in first_sql
    assert "conversations.status !=" in first_sql
    assert "conversations.updated_at desc, conversations.id desc" in first_sql
    assert " offset " not in first_sql
    assert "checkpoint" not in first_sql

    second_session = FakeSession([rows[2]])
    second_items, final_cursor = await ConversationRepository(second_session).list_owned(
        user_id="alice",
        limit=2,
        cursor=next_cursor,
    )

    assert [item.id for item in second_items] == [10]
    assert final_cursor is None
    assert {item.id for item in first_items}.isdisjoint(item.id for item in second_items)
    second_sql = _sql(second_session.statements[0])
    assert "conversations.updated_at <" in second_sql
    assert "conversations.id <" in second_sql


@pytest.mark.asyncio
async def test_messages_use_owned_chronological_keyset_and_business_tables_only():
    from app.domains.chat.repositories import MessageCursor, MessageRepository

    now = datetime(2026, 7, 14, tzinfo=UTC)
    rows = [
        Message(id=10, conversation_id=42, role="USER", content="one", created_at=now),
        Message(id=20, conversation_id=42, role="ASSISTANT", content="two", created_at=now),
        Message(
            id=30,
            conversation_id=42,
            role="USER",
            content="three",
            created_at=now + timedelta(seconds=1),
        ),
    ]
    first_session = FakeSession(rows)
    first_items, next_cursor = await MessageRepository(first_session).list_owned(
        user_id="alice",
        conversation_id=42,
        limit=2,
    )

    assert [item.id for item in first_items] == [10, 20]
    assert MessageCursor.decode(next_cursor) == MessageCursor(now, 20)
    first_sql = _sql(first_session.statements[0])
    assert "join conversations" in first_sql
    assert "conversations.user_id" in first_sql
    assert "messages.created_at asc, messages.id asc" in first_sql
    assert " offset " not in first_sql
    assert "checkpoint" not in first_sql

    second_session = FakeSession([rows[2]])
    second_items, final_cursor = await MessageRepository(second_session).list_owned(
        user_id="alice",
        conversation_id=42,
        limit=2,
        cursor=next_cursor,
    )

    assert [item.id for item in second_items] == [30]
    assert final_cursor is None
    assert {item.id for item in first_items}.isdisjoint(item.id for item in second_items)
    second_sql = _sql(second_session.statements[0])
    assert "messages.created_at >" in second_sql
    assert "messages.id >" in second_sql
