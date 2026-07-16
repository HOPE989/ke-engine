from types import SimpleNamespace
import asyncio

import pytest


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("  标题：订单索引优化  ", "订单索引优化"),
        ("“分布式事务补偿”", "分布式事务补偿"),
        ("第一行标题\n这里是解释", "第一行标题"),
        ("x" * 25, "x" * 20),
        ([{"type": "text", "text": "标题: 向量检索调优"}], "向量检索调优"),
        (" \n ", ""),
    ],
)
def test_normalize_title_enforces_plain_twenty_character_output(content, expected):
    from app.domains.chat.services.title import normalize_title

    assert normalize_title(content) == expected


class FakeModel:
    def __init__(self, *, content="标题：订单索引优化", error=None):
        self.content = content
        self.error = error
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages
        if self.error is not None:
            raise self.error
        return SimpleNamespace(content=self.content)


class FakeTransaction:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.session.commits += 1
        return None


class FakeSession:
    def __init__(self):
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def begin(self):
        return FakeTransaction(self)


class FakeSessionFactory:
    def __init__(self):
        self.calls = 0
        self.session = FakeSession()

    def __call__(self):
        self.calls += 1
        return self.session


@pytest.mark.asyncio
async def test_generate_title_calls_model_then_updates_in_a_short_transaction(monkeypatch):
    from app.domains.chat.repositories import ConversationRepository
    from app.domains.chat.services.title import (
        TITLE_SYSTEM_PROMPT,
        TitleGenerationRequest,
        generate_and_update_title,
    )

    updates = []

    async def fake_update_title(repository, *, conversation_id, title):
        updates.append((conversation_id, title))
        return True

    monkeypatch.setattr(ConversationRepository, "update_title", fake_update_title)
    model = FakeModel()
    factory = FakeSessionFactory()

    await generate_and_update_title(
        request=TitleGenerationRequest(conversation_id=42, content="帮我优化订单索引"),
        model=model,
        session_factory=factory,
    )

    assert model.messages[0].content == TITLE_SYSTEM_PROMPT
    assert model.messages[1].content == "帮我优化订单索引"
    assert updates == [(42, "订单索引优化")]
    assert factory.calls == 1
    assert factory.session.commits == 1


@pytest.mark.asyncio
async def test_empty_or_failed_title_keeps_existing_title(caplog):
    from app.domains.chat.services.title import (
        TitleGenerationRequest,
        generate_and_update_title,
    )

    request = TitleGenerationRequest(conversation_id=42, content="hello")
    empty_factory = FakeSessionFactory()
    await generate_and_update_title(
        request=request,
        model=FakeModel(content="  "),
        session_factory=empty_factory,
    )
    assert empty_factory.calls == 0

    failing_factory = FakeSessionFactory()
    await generate_and_update_title(
        request=request,
        model=FakeModel(error=RuntimeError("model failed")),
        session_factory=failing_factory,
    )
    assert failing_factory.calls == 0
    assert "conversation title generation failed" in caplog.text


@pytest.mark.asyncio
async def test_submit_keeps_task_alive_until_completion(monkeypatch):
    from app.domains.chat.services import title as title_module

    release = asyncio.Event()

    async def fake_generate_and_update_title(**kwargs):
        await release.wait()

    monkeypatch.setattr(
        title_module,
        "generate_and_update_title",
        fake_generate_and_update_title,
    )
    request = title_module.TitleGenerationRequest(conversation_id=42, content="hello")
    task = title_module.submit_title_generation(
        request=request,
        model=object(),
        session_factory=object(),
    )

    assert task in title_module._background_title_tasks
    release.set()
    await task
    await asyncio.sleep(0)
    assert task not in title_module._background_title_tasks
