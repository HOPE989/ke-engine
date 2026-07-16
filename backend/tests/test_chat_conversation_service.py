from datetime import UTC, datetime

import pytest

from app.domains.chat.shared.models import Conversation, Message


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeTransaction:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.begins += 1

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.session.commits += 1
        else:
            self.session.rollbacks += 1


class FakeSession:
    def __init__(self, *, owned_conversation=None, fail_on_type=None):
        self.owned_conversation = owned_conversation
        self.fail_on_type = fail_on_type
        self.added = []
        self.statements = []
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
        self.statements.append(statement)
        value = self.owned_conversation
        if value is not None and value.user_id not in statement.compile().params.values():
            value = None
        return FakeScalarResult(value)

    def add(self, value):
        if isinstance(value, self.fail_on_type or ()):  # pragma: no branch
            raise RuntimeError("write failed")
        self.added.append(value)


class FakeSessionFactory:
    def __init__(self, session):
        self.session = session
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.session


class FakeIdGenerator:
    def __init__(self, *values):
        self.values = iter(values)

    def next_id(self):
        return next(self.values)


class FakeTitleSubmitter:
    def __init__(self, session):
        self.session = session
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append((self.session.commits, kwargs))


@pytest.mark.asyncio
async def test_accept_first_user_turn_creates_active_conversation_and_message_atomically():
    from app.domains.chat.services.conversation import ConversationService

    session = FakeSession()
    now = datetime(2026, 7, 14, tzinfo=UTC)
    title_model = object()
    title_submitter = FakeTitleSubmitter(session)
    service = ConversationService(
        session_factory=FakeSessionFactory(session),
        id_generator=FakeIdGenerator(1001, 2001),
        title_model=title_model,
        title_submitter=title_submitter,
        now=lambda: now,
    )
    content = "  " + "x" * 300 + "  "

    turn = await service.accept_user_turn(user_id="alice", content=content)

    conversation, message = session.added
    assert isinstance(conversation, Conversation)
    assert conversation.id == 1001
    assert conversation.user_id == "alice"
    assert conversation.title == "x" * 20
    assert conversation.status == "ACTIVE"
    assert conversation.updated_at == now
    assert isinstance(message, Message)
    assert message.id == 2001
    assert message.conversation_id == 1001
    assert message.role == "USER"
    assert message.content == "x" * 300
    assert turn.conversation_id == 1001
    assert turn.user_message_id == 2001
    assert turn.content == "x" * 300
    assert (session.begins, session.commits, session.rollbacks) == (1, 1, 0)
    assert len(title_submitter.calls) == 1
    commits_at_submit, submit_kwargs = title_submitter.calls[0]
    assert commits_at_submit == 1
    assert submit_kwargs["request"].conversation_id == 1001
    assert submit_kwargs["request"].content == "x" * 300
    assert submit_kwargs["model"] is title_model


@pytest.mark.asyncio
async def test_accept_user_turn_appends_to_owned_conversation_and_updates_activity():
    from app.domains.chat.services.conversation import ConversationService

    previous = datetime(2026, 7, 13, tzinfo=UTC)
    now = datetime(2026, 7, 14, tzinfo=UTC)
    conversation = Conversation(
        id=1001,
        user_id="alice",
        title="existing",
        status="ACTIVE",
        updated_at=previous,
    )
    session = FakeSession(owned_conversation=conversation)
    title_submitter = FakeTitleSubmitter(session)
    service = ConversationService(
        session_factory=FakeSessionFactory(session),
        id_generator=FakeIdGenerator(2002),
        title_model=object(),
        title_submitter=title_submitter,
        now=lambda: now,
    )

    turn = await service.accept_user_turn(
        user_id="alice",
        content=" next question ",
        conversation_id=1001,
    )

    assert conversation.updated_at == now
    assert len(session.statements) == 1
    assert len(session.added) == 1
    assert session.added[0].conversation_id == 1001
    assert turn.user_message_id == 2002
    assert (session.begins, session.commits, session.rollbacks) == (1, 1, 0)
    assert conversation.title == "existing"
    assert title_submitter.calls == []


@pytest.mark.asyncio
async def test_blank_content_is_rejected_before_opening_session_or_transaction():
    from app.domains.chat.services.conversation import ConversationService

    factory = FakeSessionFactory(FakeSession())
    service = ConversationService(
        factory,
        FakeIdGenerator(),
        title_model=object(),
        title_submitter=FakeTitleSubmitter(factory.session),
    )

    with pytest.raises(ValueError, match="blank"):
        await service.accept_user_turn(user_id="alice", content=" \t\n ")

    assert factory.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("owned_conversation", [None, Conversation(id=1001, user_id="bob", title="x")])
async def test_missing_and_foreign_conversations_raise_same_not_found(owned_conversation):
    from app.domains.chat.services.conversation import (
        ConversationNotFound,
        ConversationService,
    )

    session = FakeSession(owned_conversation=owned_conversation)
    title_submitter = FakeTitleSubmitter(session)
    service = ConversationService(
        FakeSessionFactory(session),
        FakeIdGenerator(2001),
        title_model=object(),
        title_submitter=title_submitter,
    )

    with pytest.raises(ConversationNotFound):
        await service.accept_user_turn(
            user_id="alice",
            content="hello",
            conversation_id=1001,
        )

    assert session.added == []
    assert (session.commits, session.rollbacks) == (0, 1)
    assert title_submitter.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on_type", [Conversation, Message])
async def test_first_turn_rolls_back_when_either_write_fails(fail_on_type):
    from app.domains.chat.services.conversation import ConversationService

    session = FakeSession(fail_on_type=fail_on_type)
    title_submitter = FakeTitleSubmitter(session)
    service = ConversationService(
        FakeSessionFactory(session),
        FakeIdGenerator(1001, 2001),
        title_model=object(),
        title_submitter=title_submitter,
    )

    with pytest.raises(RuntimeError, match="write failed"):
        await service.accept_user_turn(user_id="alice", content="hello")

    assert session.commits == 0
    assert session.rollbacks == 1
    assert title_submitter.calls == []
