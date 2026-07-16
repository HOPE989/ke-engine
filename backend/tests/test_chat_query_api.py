from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.domains.chat.shared.models import Conversation, Message
from app.services.chat_api.app import create_app


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return self

    def all(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)
        self.statements = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, statement):
        self.statements.append(statement)
        value = self.results.pop(0)
        if isinstance(value, Conversation) and value.user_id not in statement.compile().params.values():
            value = None
        return FakeResult(value)


class FakeSessionFactory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self.session


class ExplodingCheckpointer:
    def __getattr__(self, name):
        raise AssertionError("query API must not read checkpoint state")


def _client_with_session(session):
    app = create_app()
    app.state.chat_deps = SimpleNamespace(
        session_factory=FakeSessionFactory(session),
        graph=ExplodingCheckpointer(),
    )
    return app, AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_chat_conversation_query_returns_current_user_newest_first_with_cursor():
    now = datetime(2026, 7, 14, tzinfo=UTC)
    rows = [
        Conversation(
            id=9007199254740993,
            user_id="alice",
            title="new",
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        ),
        Conversation(
            id=9007199254740992,
            user_id="alice",
            title="old",
            status="ACTIVE",
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(days=1),
        ),
    ]
    session = FakeSession(rows)
    app, client = _client_with_session(session)
    async with client:
        response = await client.get(
            "/api/v1/chat/conversations?limit=1",
            headers={"X-Mock-User-Id": "alice"},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["id"] for item in data["items"]] == ["9007199254740993"]
    assert data["next_cursor"]
    assert "alice" in session.statements[0].compile().params.values()


@pytest.mark.asyncio
async def test_chat_message_query_is_chronological_with_string_ids_and_no_checkpoint_read():
    now = datetime(2026, 7, 14, tzinfo=UTC)
    conversation = Conversation(id=42, user_id="alice", title="chat", status="ACTIVE")
    messages = [
        Message(id=101, conversation_id=42, role="USER", content="one", created_at=now),
        Message(
            id=102,
            conversation_id=42,
            parent_message_id=101,
            role="ASSISTANT",
            content="two",
            created_at=now + timedelta(seconds=1),
        ),
    ]
    session = FakeSession(conversation, messages)
    app, client = _client_with_session(session)
    async with client:
        response = await client.get(
            "/api/v1/chat/conversations/42/messages",
            headers={"X-Mock-User-Id": "alice"},
        )

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [(item["id"], item["conversation_id"], item["parent_message_id"]) for item in items] == [
        ("101", "42", None),
        ("102", "42", "101"),
    ]
    assert [item["content"] for item in items] == ["one", "two"]


@pytest.mark.asyncio
@pytest.mark.parametrize("conversation", [None, Conversation(id=42, user_id="bob", title="x")])
async def test_chat_message_query_conceals_missing_and_foreign_conversations(conversation):
    session = FakeSession(conversation)
    app, client = _client_with_session(session)
    async with client:
        response = await client.get(
            "/api/v1/chat/conversations/42/messages",
            headers={"X-Mock-User-Id": "alice"},
        )

    assert response.status_code == 404
    assert response.json() == {"code": 404, "message": "conversation not found", "data": None}
