import json
from types import SimpleNamespace

from langchain_core.messages import AIMessageChunk
import pytest
from httpx import ASGITransport, AsyncClient

from app.domains.chat.graph.routing import LLM_NODE
from app.domains.chat.services.runtime import CompletionProducerRegistry
from app.domains.chat.shared.models import Conversation
from app.services.chat_api.app import create_app


class FakeResult:
    def __init__(self, value, *, rowcount=1):
        self.value = value
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self.value


class FakeTransaction:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.begins += 1

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            if self.session.fail_commit_at == self.session.commits + 1:
                raise RuntimeError("assistant commit failed")
            self.session.commits += 1
        else:
            self.session.rollbacks += 1


class FakeSession:
    def __init__(self, *, owned_conversation=None, fail_commit_at=None):
        self.owned_conversation = owned_conversation
        self.fail_commit_at = fail_commit_at
        self.added = []
        self.begins = 0
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def begin(self):
        return FakeTransaction(self)

    async def execute(self, statement):
        value = self.owned_conversation
        if value is not None and value.user_id not in statement.compile().params.values():
            value = None
        return FakeResult(value)

    def add(self, value):
        self.added.append(value)


class FakeSessionFactory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self.session


class FakeIdGenerator:
    def __init__(self, *values):
        self.values = iter(values)

    def next_id(self):
        return next(self.values)


class FakeGraph:
    async def astream_events(self, *args, **kwargs):
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": AIMessageChunk(content="answer")},
            "metadata": {"langgraph_node": LLM_NODE},
        }


class FailingGraph(FakeGraph):
    async def astream_events(self, *args, **kwargs):
        async for event in super().astream_events(*args, **kwargs):
            yield event
        raise RuntimeError("graph failed")


class FakeTitleModel:
    async def ainvoke(self, messages):
        return SimpleNamespace(content="测试会话标题")


def _parse_sse(body):
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        events.append(
            (
                lines[0].removeprefix("event: "),
                json.loads(lines[1].removeprefix("data: ")),
            )
        )
    return events


def _app_with_runtime(session, ids, *, graph=None):
    app = create_app()
    app.state.chat_deps = SimpleNamespace(
        session_factory=FakeSessionFactory(session),
        id_generator=FakeIdGenerator(*ids),
        graph=graph or FakeGraph(),
        model=object(),
        title_model=FakeTitleModel(),
        producer_registry=CompletionProducerRegistry(shutdown_timeout=1),
    )
    return app


@pytest.mark.asyncio
async def test_completion_metadata_creates_first_conversation_and_sets_stream_headers():
    session = FakeSession()
    app = _app_with_runtime(session, [1001, 2001, 3001])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat/completions",
            headers={"X-Mock-User-Id": "alice"},
            json={"content": " hello "},
        )

    events = _parse_sse(response.text)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert events[0] == (
        "metadata",
        {"conversation_id": "1001", "user_message_id": "2001"},
    )
    assert isinstance(session.added[0], Conversation)
    assert session.added[0].user_id == "alice"
    assert session.commits >= 1


@pytest.mark.asyncio
async def test_completion_metadata_reuses_owned_conversation():
    conversation = Conversation(id=42, user_id="alice", title="existing", status="ACTIVE")
    session = FakeSession(owned_conversation=conversation)
    app = _app_with_runtime(session, [2002, 3002])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat/completions",
            headers={"X-Mock-User-Id": "alice"},
            json={"conversation_id": "42", "content": "next"},
        )

    assert _parse_sse(response.text)[0][1] == {
        "conversation_id": "42",
        "user_message_id": "2002",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"content": "   "},
        {"content": "hello", "model": "client-model"},
        {"content": "hello", "idempotency_key": "key"},
        {"content": "hello", "thread_id": "42"},
    ],
)
async def test_completion_validation_rejects_invalid_or_unsupported_input_without_writes(payload):
    session = FakeSession()
    app = _app_with_runtime(session, [])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat/completions", json=payload)

    assert response.status_code == 422
    assert session.added == []
    assert session.begins == 0


@pytest.mark.asyncio
async def test_completion_ownership_conceals_foreign_conversation():
    session = FakeSession(
        owned_conversation=Conversation(id=42, user_id="bob", title="foreign")
    )
    app = _app_with_runtime(session, [2001])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat/completions",
            headers={"X-Mock-User-Id": "alice"},
            json={"conversation_id": "42", "content": "hello"},
        )

    assert response.status_code == 404
    assert response.json() == {"code": 404, "message": "conversation not found", "data": None}
    assert session.added == []


@pytest.mark.asyncio
async def test_completion_terminal_success_has_no_heartbeat_or_replay_protocol():
    session = FakeSession()
    app = _app_with_runtime(session, [1001, 2001, 3001])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat/completions",
            json={"content": "hello"},
            headers={"Last-Event-ID": "unsupported"},
        )

    assert [event for event, _ in _parse_sse(response.text)] == [
        "metadata",
        "content_delta",
        "completed",
    ]
    assert "heartbeat" not in response.text
    assert "\nid:" not in response.text
    assert "\nretry:" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("session", "graph"),
    [
        (FakeSession(), FailingGraph()),
        (FakeSession(fail_commit_at=2), FakeGraph()),
    ],
)
async def test_completion_terminal_failure_emits_error_without_completed(session, graph):
    app = _app_with_runtime(session, [1001, 2001, 3001], graph=graph)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat/completions",
            json={"content": "hello"},
        )

    event_names = [event for event, _ in _parse_sse(response.text)]
    assert event_names == ["metadata", "content_delta", "error"]
    assert "completed" not in event_names
    assert event_names.count("error") == 1
