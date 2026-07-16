# Chat Conversation Title Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新会话提交首条 USER 消息后，立即保留前 20 个字符的临时标题，并在当前 FastAPI worker 的事件循环上异步调用 `qwen3.6-flash` 更新正式标题。

**Architecture:** `ConversationService` 继续负责新会话与 USER 消息的原子事务，并在事务成功提交后直接调用轻量标题提交函数。标题模块用 `asyncio.create_task()` 创建进程内 best-effort task，以模块级集合保持强引用，异步模型调用完成后使用独立短事务更新标题；任务失败只记录日志并保留原有标题。

**Tech Stack:** Python 3.11、FastAPI/Uvicorn、asyncio、LangChain `ChatOpenAI`、SQLAlchemy AsyncIO、PostgreSQL、pytest、pytest-asyncio

## Global Constraints

- 标题模型名固定为 `qwen3.6-flash`，不得增加配置项。
- 临时标题和正式标题均最多 20 个 Python 字符；数据库列继续保持 `VARCHAR(255)`。
- 只在新会话创建时提交一次标题任务；已有会话追加消息时保留原标题且不提交任务。
- 不增加 `is_first_turn` 或其他标题字段到 `AcceptedUserTurn`。
- 标题 task 必须在 USER 消息事务提交后创建，并使用独立 `AsyncSession`。
- 不引入 `TitleScheduler`、Celery、Kafka、重试、关闭等待、前端事件或数据库迁移。
- 标题更新不得改变 `conversations.updated_at`。
- 标题任务是进程内 best-effort 任务；worker 退出时允许丢失。

---

## File Structure

- Create: `backend/app/domains/chat/services/title.py` — 标题请求、提示词、输出清洗、模型调用、数据库更新和直接 task 提交。
- Create: `backend/tests/test_chat_title_generation.py` — 标题纯函数、异步生成、错误隔离和 task 强引用测试。
- Modify: `backend/app/domains/chat/repositories/conversation_repository.py` — 增加不刷新活跃时间的内部标题更新方法。
- Modify: `backend/tests/test_chat_repositories.py` — 验证标题 UPDATE 的过滤条件与 `updated_at` 保持行为。
- Modify: `backend/app/domains/chat/services/conversation.py` — 临时标题改为 20 字，并在事务提交后提交标题任务。
- Modify: `backend/tests/test_chat_conversation_service.py` — 验证新旧会话触发规则、提交顺序和回滚边界。
- Modify: `backend/app/services/chat_api/deps.py` — 创建固定标题模型并放入 `ChatApiDeps`。
- Modify: `backend/app/services/chat_api/router.py` — 向 `ConversationService` 注入标题模型。
- Modify: `backend/tests/test_chat_api_lifespan.py` — 验证主模型与标题模型的启动装配。
- Modify: `backend/tests/test_chat_completion_api.py` — 为 API 测试提供异步标题模型与 UPDATE 测试结果。

---

### Task 1: Add a title-only repository update

**Files:**
- Modify: `backend/app/domains/chat/repositories/conversation_repository.py:12-15,55-101`
- Test: `backend/tests/test_chat_repositories.py`

**Interfaces:**
- Consumes: `Conversation`, `ConversationStatus`, SQLAlchemy `update()`。
- Produces: `ConversationRepository.update_title(*, conversation_id: int, title: str) -> bool`，供标题生成模块在独立事务内调用。

- [ ] **Step 1: Write the failing repository test**

在 `backend/tests/test_chat_repositories.py` 增加独立的 UPDATE fake，避免改变现有分页 fake：

```python
class FakeUpdateResult:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class FakeUpdateSession:
    def __init__(self, *, rowcount=1):
        self.rowcount = rowcount
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeUpdateResult(self.rowcount)


@pytest.mark.asyncio
async def test_update_title_preserves_activity_time_and_ignores_deleted_conversations():
    from app.domains.chat.repositories import ConversationRepository

    session = FakeUpdateSession()
    updated = await ConversationRepository(session).update_title(
        conversation_id=42,
        title="订单索引优化",
    )

    assert updated is True
    statement = session.statements[0]
    sql = _sql(statement).replace(" ", "")
    assert "updateconversationssettitle=" in sql
    assert "updated_at=conversations.updated_at" in sql
    assert "conversations.id=" in sql
    assert "conversations.status!=" in sql
    assert "订单索引优化" in statement.compile().params.values()
```

- [ ] **Step 2: Run the repository test to verify it fails**

Run from `backend/`:

```bash
uv run python -m pytest tests/test_chat_repositories.py::test_update_title_preserves_activity_time_and_ignores_deleted_conversations -q
```

Expected: FAIL with `AttributeError: 'ConversationRepository' object has no attribute 'update_title'`.

- [ ] **Step 3: Implement the minimal repository method**

在 `conversation_repository.py` 的 SQLAlchemy imports 加入 `update`，并在 `ConversationRepository` 中加入：

```python
from sqlalchemy import and_, or_, select, update


async def update_title(self, *, conversation_id: int, title: str) -> bool:
    """更新未删除会话的标题，同时保持业务活跃时间不变。"""

    statement = (
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.status != ConversationStatus.DELETED.value,
        )
        .values(
            title=title,
            updated_at=Conversation.updated_at,
        )
    )
    result = await self._session.execute(statement)
    return result.rowcount > 0
```

显式提供 `updated_at=Conversation.updated_at`，防止 SQLAlchemy 的 `onupdate=func.now()` 在标题 UPDATE 中刷新会话排序时间。

- [ ] **Step 4: Run repository tests**

Run from `backend/`:

```bash
uv run python -m pytest tests/test_chat_repositories.py -q
```

Expected: all tests in `test_chat_repositories.py` PASS.

- [ ] **Step 5: Commit the repository slice**

```bash
git add backend/app/domains/chat/repositories/conversation_repository.py backend/tests/test_chat_repositories.py
git commit -m "feat(chat): add title-only conversation update"
```

---

### Task 2: Implement lightweight asynchronous title generation

**Files:**
- Create: `backend/app/domains/chat/services/title.py`
- Create: `backend/tests/test_chat_title_generation.py`

**Interfaces:**
- Consumes: `ConversationRepository.update_title(conversation_id: int, title: str) -> bool` from Task 1, a ChatOpenAI-compatible object exposing `ainvoke(messages)`, and an async session factory.
- Produces:
  - `TITLE_MODEL: str = "qwen3.6-flash"`
  - `TitleGenerationRequest(conversation_id: int, content: str)`
  - `normalize_title(content: object) -> str`
  - `generate_and_update_title(*, request, model, session_factory) -> None`
  - `submit_title_generation(*, request, model, session_factory) -> asyncio.Task[None]`

- [ ] **Step 1: Write failing normalization tests**

创建 `backend/tests/test_chat_title_generation.py`：

```python
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
```

- [ ] **Step 2: Run normalization tests to verify they fail**

Run from `backend/`:

```bash
uv run python -m pytest tests/test_chat_title_generation.py::test_normalize_title_enforces_plain_twenty_character_output -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.domains.chat.services.title'`.

- [ ] **Step 3: Implement request, prompt, content extraction, and normalization**

创建 `backend/app/domains/chat/services/title.py`，先写入纯函数部分：

```python
"""会话标题的轻量异步生成与 best-effort 持久化。"""

import asyncio
from dataclasses import dataclass
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.domains.chat.repositories import ConversationRepository

TITLE_MODEL = "qwen3.6-flash"
TITLE_MAX_LENGTH = 20
TITLE_SYSTEM_PROMPT = (
    "根据用户消息概括会话主题。只输出标题，不要解释，不要添加引号，最多20个字符。"
)

logger = logging.getLogger(__name__)
_TITLE_PREFIX = re.compile(r"^标题\s*[:：]\s*")
_OUTER_QUOTES = (("\"", "\""), ("'", "'"), ("“", "”"), ("‘", "’"))
_background_title_tasks: set[asyncio.Task[None]] = set()


@dataclass(frozen=True, slots=True)
class TitleGenerationRequest:
    conversation_id: int
    content: str


def _extract_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "".join(parts)


def normalize_title(content: object) -> str:
    text = _extract_text(content).strip()
    if not text:
        return ""
    text = text.splitlines()[0].strip()
    text = _TITLE_PREFIX.sub("", text).strip()
    for opening, closing in _OUTER_QUOTES:
        if len(text) >= 2 and text.startswith(opening) and text.endswith(closing):
            text = text[len(opening) : -len(closing)].strip()
            break
    return text[:TITLE_MAX_LENGTH]
```

- [ ] **Step 4: Run normalization tests**

Run from `backend/`:

```bash
uv run python -m pytest tests/test_chat_title_generation.py::test_normalize_title_enforces_plain_twenty_character_output -q
```

Expected: parameterized normalization test PASS.

- [ ] **Step 5: Add failing async generation and task-retention tests**

在同一测试文件加入以下 fakes 与测试：

```python
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
async def test_empty_or_failed_title_keeps_existing_title(monkeypatch, caplog):
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
```

- [ ] **Step 6: Run async tests to verify missing functions fail**

Run from `backend/`:

```bash
uv run python -m pytest tests/test_chat_title_generation.py -q
```

Expected: normalization passes; async tests FAIL because `generate_and_update_title` and `submit_title_generation` are missing.

- [ ] **Step 7: Implement model invocation, isolated update, and direct task submission**

在 `title.py` 追加：

```python
async def generate_and_update_title(
    *,
    request: TitleGenerationRequest,
    model: Any,
    session_factory: Any,
) -> None:
    """生成并 best-effort 更新标题；普通失败不得逃逸到主请求。"""

    try:
        response = await model.ainvoke(
            [
                SystemMessage(content=TITLE_SYSTEM_PROMPT),
                HumanMessage(content=request.content),
            ]
        )
        title = normalize_title(response.content)
        if not title:
            return

        async with session_factory() as session:
            async with session.begin():
                await ConversationRepository(session).update_title(
                    conversation_id=request.conversation_id,
                    title=title,
                )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "conversation title generation failed",
            extra={"conversation_id": request.conversation_id},
        )


def submit_title_generation(
    *,
    request: TitleGenerationRequest,
    model: Any,
    session_factory: Any,
) -> asyncio.Task[None]:
    """在当前事件循环直接创建标题 task，并在完成前保持强引用。"""

    task = asyncio.create_task(
        generate_and_update_title(
            request=request,
            model=model,
            session_factory=session_factory,
        ),
        name=f"conversation-title:{request.conversation_id}",
    )
    _background_title_tasks.add(task)
    task.add_done_callback(_background_title_tasks.discard)
    return task
```

- [ ] **Step 8: Run title-generation tests**

Run from `backend/`:

```bash
uv run python -m pytest tests/test_chat_title_generation.py -q
```

Expected: all title-generation tests PASS with no unhandled-task warnings.

- [ ] **Step 9: Commit the title runtime slice**

```bash
git add backend/app/domains/chat/services/title.py backend/tests/test_chat_title_generation.py
git commit -m "feat(chat): generate conversation titles asynchronously"
```

---

### Task 3: Trigger title generation after the new-conversation transaction

**Files:**
- Modify: `backend/app/domains/chat/services/conversation.py:1-124`
- Modify: `backend/tests/test_chat_conversation_service.py`

**Interfaces:**
- Consumes: `TitleGenerationRequest` and `submit_title_generation()` from Task 2.
- Produces: `ConversationService(session_factory, id_generator, title_model, *, title_submitter=submit_title_generation, now=None)`。`AcceptedUserTurn` 的字段保持不变。

- [ ] **Step 1: Update service tests to describe the new transaction boundary**

在 `test_chat_conversation_service.py` 增加：

```python
class FakeTitleSubmitter:
    def __init__(self, session):
        self.session = session
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append((self.session.commits, kwargs))
```

将首轮测试的 service 构造和断言改为：

```python
title_model = object()
title_submitter = FakeTitleSubmitter(session)
service = ConversationService(
    session_factory=FakeSessionFactory(session),
    id_generator=FakeIdGenerator(1001, 2001),
    title_model=title_model,
    title_submitter=title_submitter,
    now=lambda: now,
)

assert conversation.title == "x" * 20
assert len(title_submitter.calls) == 1
commits_at_submit, submit_kwargs = title_submitter.calls[0]
assert commits_at_submit == 1
assert submit_kwargs["request"].conversation_id == 1001
assert submit_kwargs["request"].content == "x" * 300
assert submit_kwargs["model"] is title_model
```

在已有会话测试中使用同一 fake，并追加：

```python
assert conversation.title == "existing"
assert title_submitter.calls == []
```

在两个回滚参数用例中传入 fake，并追加：

```python
assert title_submitter.calls == []
```

其余 `ConversationService` 构造统一传入 `title_model=object()` 和 fake submitter，保证单元测试不会创建真实 background task。

- [ ] **Step 2: Run service tests to verify they fail**

Run from `backend/`:

```bash
uv run python -m pytest tests/test_chat_conversation_service.py -q
```

Expected: FAIL because the constructor has no `title_model`/`title_submitter`, and the temporary title is still 255 characters.

- [ ] **Step 3: Implement post-commit task submission without changing AcceptedUserTurn**

修改 `conversation.py`：

```python
from app.domains.chat.services.title import (
    TitleGenerationRequest,
    submit_title_generation,
)


def _title_from_content(content: str) -> str:
    """从首条规范化消息截取 20 个字符作为新会话临时标题。"""

    return content[:20]
```

构造函数增加依赖：

```python
def __init__(
    self,
    session_factory: Any,
    id_generator: Any,
    title_model: Any,
    *,
    title_submitter: Any = submit_title_generation,
    now: Any = None,
) -> None:
    self._session_factory = session_factory
    self._id_generator = id_generator
    self._title_model = title_model
    self._title_submitter = title_submitter
    self._now = now or (lambda: datetime.now(UTC))
```

在事务前初始化请求，在新会话分支赋值，并在两个事务上下文都退出后提交：

```python
normalized = _normalize_content(content)
title_request: TitleGenerationRequest | None = None
async with self._session_factory() as session:
    async with session.begin():
        timestamp = self._now()
        if conversation_id is None:
            conversation_id = self._id_generator.next_id()
            conversation = Conversation(
                id=conversation_id,
                user_id=user_id,
                title=_title_from_content(normalized),
                status=ConversationStatus.ACTIVE.value,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(conversation)
            title_request = TitleGenerationRequest(
                conversation_id=conversation_id,
                content=normalized,
            )
        else:
            conversation = await ConversationRepository(session).get_owned(
                conversation_id=conversation_id,
                user_id=user_id,
            )
            if conversation is None:
                raise ConversationNotFound()
            conversation.updated_at = timestamp

        user_message_id = self._id_generator.next_id()
        session.add(
            Message(
                id=user_message_id,
                conversation_id=conversation_id,
                role=MessageRole.USER.value,
                content=normalized,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )

if title_request is not None:
    self._title_submitter(
        request=title_request,
        model=self._title_model,
        session_factory=self._session_factory,
    )
```

保持现有 `AcceptedUserTurn(conversation_id, user_message_id, content)` 返回结构不变。

- [ ] **Step 4: Run service tests**

Run from `backend/`:

```bash
uv run python -m pytest tests/test_chat_conversation_service.py -q
```

Expected: all conversation service tests PASS; new conversation submits exactly once after commit, existing/rollback paths submit zero times.

- [ ] **Step 5: Commit the transaction-trigger slice**

```bash
git add backend/app/domains/chat/services/conversation.py backend/tests/test_chat_conversation_service.py
git commit -m "feat(chat): trigger title generation after conversation commit"
```

---

### Task 4: Wire the fixed title model into Chat API and run regressions

**Files:**
- Modify: `backend/app/services/chat_api/deps.py:55-116`
- Modify: `backend/app/services/chat_api/router.py:57-72`
- Modify: `backend/tests/test_chat_api_lifespan.py`
- Modify: `backend/tests/test_chat_completion_api.py`

**Interfaces:**
- Consumes: `TITLE_MODEL` from Task 2 and the new `ConversationService` constructor from Task 3.
- Produces: `ChatApiDeps.title_model` initialized with `create_chat_model(settings, model="qwen3.6-flash")`。

- [ ] **Step 1: Write the failing lifespan expectation**

在 `test_chat_api_lifespan.py` 中把模型 fake 改为按模型名返回不同对象：

```python
chat_model = object()
title_model = object()

def fake_create_chat_model(settings, *, model):
    calls.append(f"model_create:{model}")
    if model == "gpt-test":
        return chat_model
    if model == "qwen3.6-flash":
        return title_model
    raise AssertionError(f"unexpected model: {model}")
```

把 builder 的启动顺序和最终依赖断言更新为：

```python
assert calls == [
    "database_open",
    "model_create:gpt-test",
    "model_create:qwen3.6-flash",
    "saver_open",
    "build_graph",
]

assert application.state.chat_deps == deps.ChatApiDeps(
    session_factory=session_factory,
    id_generator=application.state.chat_deps.id_generator,
    graph=graph,
    model=chat_model,
    title_model=title_model,
    producer_registry=registry,
)
```

- [ ] **Step 2: Run lifespan test to verify it fails**

Run from `backend/`:

```bash
uv run python -m pytest tests/test_chat_api_lifespan.py::test_chat_lifespan_compiles_after_model_and_saver_and_closes_in_order -q
```

Expected: FAIL because only the configured chat model is created and `ChatApiDeps` has no `title_model` field.

- [ ] **Step 3: Wire title_model in lifespan and Router**

修改 `deps.py`：

```python
from app.domains.chat.services.title import TITLE_MODEL


@dataclass(frozen=True, slots=True)
class ChatApiDeps:
    session_factory: Any
    id_generator: Any
    graph: Any
    model: Any
    title_model: Any
    producer_registry: Any
```

在 lifespan 中紧接主模型创建标题模型，并放入依赖：

```python
model = create_chat_model(settings, model=settings.openai_model)
title_model = create_chat_model(settings, model=TITLE_MODEL)
saver = await stack.enter_async_context(postgres_checkpointer(settings.database_url))

application.state.chat_deps = ChatApiDeps(
    session_factory=session_factory,
    id_generator=SnowflakeIdGenerator(worker_id=settings.snowflake_worker_id),
    graph=graph,
    model=model,
    title_model=title_model,
    producer_registry=producer_registry,
)
```

修改 `router.py` 的 service 构造：

```python
turn = await ConversationService(
    chat_deps.session_factory,
    chat_deps.id_generator,
    chat_deps.title_model,
).accept_user_turn(
    user_id=principal.user_id,
    content=request.content,
    conversation_id=(
        int(request.conversation_id)
        if request.conversation_id is not None
        else None
    ),
)
```

- [ ] **Step 4: Adapt completion API fakes to the direct title task**

在 `test_chat_completion_api.py` 加入可立即返回的标题模型，并让 UPDATE 结果暴露 `rowcount`：

```python
class FakeResult:
    def __init__(self, value, *, rowcount=1):
        self.value = value
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self.value


class FakeTitleModel:
    async def ainvoke(self, messages):
        return SimpleNamespace(content="测试会话标题")
```

在 `_app_with_runtime()` 的依赖中加入：

```python
title_model=FakeTitleModel(),
```

这让新会话 API 测试实际执行轻量 background task，但不访问网络。已有会话测试不会提交标题任务。

- [ ] **Step 5: Run focused Chat API tests**

Run from `backend/`:

```bash
uv run python -m pytest tests/test_chat_api_lifespan.py tests/test_chat_completion_api.py -q
```

Expected: all focused lifespan and completion API tests PASS; no pending-task or unhandled-task warnings.

- [ ] **Step 6: Run the complete backend regression suite**

Run from `backend/`:

```bash
uv run python -m pytest -q
```

Expected: all backend tests PASS. Tests marked `integration` may require the repository's local PostgreSQL/infrastructure; if unavailable, run the default project test command and report infrastructure-only failures separately rather than weakening tests.

- [ ] **Step 7: Inspect the final diff and verify scope**

Run from repository root:

```bash
git diff --check
git status --short
git diff --stat
```

Expected:

- no whitespace errors;
- only the files named in this plan are modified;
- no Alembic migration, frontend file, OpenSpec artifact, config field, Scheduler, Celery, or Kafka change appears.

- [ ] **Step 8: Commit the wiring and regression slice**

```bash
git add backend/app/services/chat_api/deps.py backend/app/services/chat_api/router.py backend/tests/test_chat_api_lifespan.py backend/tests/test_chat_completion_api.py
git commit -m "feat(chat): wire fixed conversation title model"
```

---

## Final Verification

Run from `backend/`:

```bash
uv run python -m pytest tests/test_chat_repositories.py tests/test_chat_title_generation.py tests/test_chat_conversation_service.py tests/test_chat_api_lifespan.py tests/test_chat_completion_api.py -q
uv run python -m pytest -q
```

Then run from repository root:

```bash
git status --short
git log -5 --oneline
```

Expected: focused and complete suites pass, the worktree is clean after the four implementation commits, and the design constraints remain satisfied.
