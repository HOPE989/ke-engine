# Chat Conversation Redis Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用一把 conversation 级 Redis 分布式锁串行化整次 Chat completion，并补齐 Business Understanding Prompt 的多轮继承与三路示例契约。

**Architecture:** 复用 `python-redis-lock` 和现有同步 Redis client，锁名固定为 `chat:conversation:{conversation_id}:completion`，使用 expiry 与 `auto_renewal=True`。`ConversationService` 在所有权校验后、USER 写入前非阻塞获取锁，返回同时携带稳定用户轮次与锁句柄的 `AcceptedCompletion`; `CompletionProducerRegistry` 在独立后台 task 的 `finally` 中释放锁，因此浏览器断连不缩短持锁周期。

**Tech Stack:** Python 3.11+、FastAPI、SQLAlchemy Async、Redis 7、redis-py 6、python-redis-lock 4、pytest/pytest-asyncio、OpenSpec。

## Global Constraints

- 同一 conversation 同时只允许一个 active completion；不同 conversation 不共享锁。
- missing/foreign conversation 必须在观察锁状态前保持统一 404。
- 锁必须在 USER 消息写入前取得，并覆盖 checkpoint inspect/start/resume、Graph、ASSISTANT commit 与 terminal 收口。
- 锁冲突返回 HTTP 409，且不得写 USER、不得访问 Graph。
- Redis 不可用时 fail closed，返回 HTTP 503，且不得写 USER、不得访问 Graph。
- 客户端断连仅 detach subscriber；锁只能由后台 task 的 success/error/cancel/shutdown `finally` 释放。
- 使用现有 `python-redis-lock`，不新增 dependency，不引入 lease/task/fencing 状态机或进程内锁。
- 所有同步 Redis 锁操作通过 `asyncio.to_thread` 调用，禁止阻塞事件循环。
- 严格执行 RED → Verify RED → GREEN → Verify GREEN；每个行为修复先看到目标失败。

---

## File Map

- `backend/app/infrastructure/redis.py`: 只负责构造 Redis client 和命名明确的分布式锁对象。
- `backend/app/core/config.py`: 声明 Chat completion 锁的 crash-recovery expiry 配置。
- `backend/app/domains/chat/services/completion_lock.py`: 负责异步 acquire/release 包装、锁冲突与基础设施错误。
- `backend/app/domains/chat/services/conversation.py`: 在业务所有权检查后取得锁，在同一事务中提交 USER，并返回锁所有权。
- `backend/app/domains/chat/services/runtime.py`: Registry 接管锁，在后台 Producer task 的 `finally` 释放。
- `backend/app/services/chat_api/deps.py`: 启动期创建/关闭 Redis client，并注入 bound lock factory。
- `backend/app/services/chat_api/router.py`: 映射 404/409/503，并在 Registry 尚未接管时负责失败释放。
- `backend/app/domains/chat/graph/business_understanding/prompt.py`: 明确上下文继承、禁止臆造和三路合法示例。
- `backend/tests/test_chat_completion_lock.py`: 锁工厂、异步包装和真实 Redis 互斥测试。
- `backend/tests/test_chat_conversation_service.py`: 锁在 USER 写入前取得、冲突/Redis 故障回滚测试。
- `backend/tests/test_chat_completion_api.py`: HTTP 404/409/503 与 Graph 零调用测试。
- `backend/tests/test_chat_completion_disconnect.py`: detach 后仍持锁以及后台完成/关闭释放测试。
- `backend/tests/test_chat_api_lifespan.py`: Redis client 与 lock factory 生命周期装配测试。
- `backend/tests/test_business_understanding_prompt.py`: Prompt 明确规则和三路示例测试。

---

### Task 1: Redis Lock Factory and Async Ownership Wrapper

**Files:**

- Modify: `backend/app/infrastructure/redis.py`
- Modify: `backend/app/core/config.py`
- Create: `backend/app/domains/chat/services/completion_lock.py`
- Create: `backend/tests/test_chat_completion_lock.py`
- Modify: `backend/tests/test_document_config.py`

**Interfaces:**

- Produces: `chat_completion_lock(*, redis_client: Any, conversation_id: int, expire_seconds: int) -> redis_lock.Lock`.
- Produces: `ConversationBusy`, `ConversationLockUnavailable`.
- Produces: `async acquire_completion_lock(lock_factory: Callable[[int], Any], conversation_id: int) -> Any`.
- Produces: `async release_completion_lock(lock: Any) -> None`.
- Produces setting: `chat_completion_lock_expire_seconds: int = 120` with `gt=0`.

- [ ] **Step 1: Write the failing lock factory test**

```python
def test_chat_completion_lock_uses_one_conversation_key_and_auto_renewal(monkeypatch):
    captured = {}
    monkeypatch.setattr(redis_infrastructure.redis_lock, "Lock", lambda client, **kwargs: captured.update(client=client, **kwargs) or object())

    redis_infrastructure.chat_completion_lock(
        redis_client="redis-client",
        conversation_id=42,
        expire_seconds=120,
    )

    assert captured == {
        "client": "redis-client",
        "name": "chat:conversation:42:completion",
        "expire": 120,
        "auto_renewal": True,
    }
```

- [ ] **Step 2: Run the factory test and verify RED**

Run: `Set-Location backend; uv run pytest tests/test_chat_completion_lock.py::test_chat_completion_lock_uses_one_conversation_key_and_auto_renewal -q`

Expected: FAIL because `chat_completion_lock` does not exist.

- [ ] **Step 3: Add the minimal factory and positive configuration field**

```python
def chat_completion_lock(*, redis_client: Any, conversation_id: int, expire_seconds: int):
    return redis_lock.Lock(
        redis_client,
        name=f"chat:conversation:{conversation_id}:completion",
        expire=expire_seconds,
        auto_renewal=True,
    )
```

```python
chat_completion_lock_expire_seconds: int = Field(
    default=120,
    gt=0,
    validation_alias="CHAT_COMPLETION_LOCK_EXPIRE_SECONDS",
    description="startup-only: crash-recovery expiry for the auto-renewed Chat completion lock.",
)
```

- [ ] **Step 4: Write failing async acquire/release behavior tests**

```python
@pytest.mark.asyncio
async def test_acquire_completion_lock_returns_owned_lock():
    lock = FakeLock(acquired=True)
    assert await acquire_completion_lock(lambda **_: lock, 42) is lock

@pytest.mark.asyncio
async def test_acquire_completion_lock_maps_busy_and_redis_failure():
    with pytest.raises(ConversationBusy):
        await acquire_completion_lock(lambda **_: FakeLock(acquired=False), 42)
    with pytest.raises(ConversationLockUnavailable):
        await acquire_completion_lock(lambda **_: FakeLock(acquire_error=OSError("redis down")), 42)
```

- [ ] **Step 5: Run the wrapper tests and verify RED**

Run: `Set-Location backend; uv run pytest tests/test_chat_completion_lock.py -q -k "acquire or release"`

Expected: FAIL because the wrapper module and exceptions do not exist.

- [ ] **Step 6: Implement minimal async wrappers**

```python
class ConversationBusy(Exception):
    pass

class ConversationLockUnavailable(Exception):
    pass

async def acquire_completion_lock(lock_factory, conversation_id: int):
    lock = lock_factory(conversation_id=conversation_id)
    try:
        acquired = await asyncio.to_thread(lock.acquire, blocking=False)
    except Exception as exc:
        raise ConversationLockUnavailable() from exc
    if not acquired:
        raise ConversationBusy()
    return lock

async def release_completion_lock(lock):
    try:
        await asyncio.to_thread(lock.release)
    except Exception:
        logger.exception("failed to release chat completion lock")
```

- [ ] **Step 7: Verify Task 1 GREEN**

Run: `Set-Location backend; uv run pytest tests/test_chat_completion_lock.py tests/test_document_config.py -q`

Expected: all tests PASS.

- [ ] **Step 8: Commit Task 1**

```powershell
git add backend/app/infrastructure/redis.py backend/app/core/config.py backend/app/domains/chat/services/completion_lock.py backend/tests/test_chat_completion_lock.py backend/tests/test_document_config.py
git commit -m "feat(chat): add conversation completion lock"
```

---

### Task 2: Acquire Before USER Persistence and Transfer Ownership

**Files:**

- Modify: `backend/app/domains/chat/services/conversation.py`
- Modify: `backend/app/domains/chat/services/runtime.py`
- Modify: `backend/app/services/chat_api/router.py`
- Modify: `backend/tests/test_chat_conversation_service.py`
- Modify: `backend/tests/test_chat_completion_api.py`
- Modify: `backend/tests/test_chat_completion_disconnect.py`

**Interfaces:**

- Produces: `AcceptedCompletion(turn: AcceptedUserTurn, lock: Any)`.
- Changes: `ConversationService(session_factory, id_generator, title_model, *, completion_lock_factory, title_submitter=submit_title_generation, now=None).accept_user_turn(*, user_id: str, content: str, conversation_id: int | None = None) -> AcceptedCompletion`.
- Changes: `CompletionProducerRegistry.start(*, producer_factory: Callable[[Any], CompletionProducer], turn: AcceptedUserTurn, completion_lock: Any, user_id: str) -> CompletionSubscriber`.

- [ ] **Step 1: Write failing service tests for acquire-before-write and owner concealment**

```python
@pytest.mark.asyncio
async def test_accept_user_turn_acquires_conversation_lock_before_user_write():
    calls = []
    accepted = await service_with_lock(calls, acquired=True).accept_user_turn(
        user_id="alice", content="next", conversation_id=42
    )
    assert calls.index("lock_acquire:42") < calls.index("message_add")
    assert accepted.turn.content == "next"
    assert accepted.lock is not None

@pytest.mark.asyncio
async def test_foreign_conversation_does_not_observe_lock_state():
    with pytest.raises(ConversationNotFound):
        await foreign_service_with_lock(calls).accept_user_turn(
            user_id="alice", content="next", conversation_id=42
        )
    assert "lock_factory" not in calls
```

- [ ] **Step 2: Write failing busy and Redis-unavailable rollback tests**

```python
@pytest.mark.parametrize(
    ("lock", "error"),
    [(FakeLock(acquired=False), ConversationBusy), (FakeLock(acquire_error=OSError()), ConversationLockUnavailable)],
)
@pytest.mark.asyncio
async def test_lock_admission_failure_rolls_back_before_user_write(lock, error):
    with pytest.raises(error):
        await service_with_specific_lock(lock).accept_user_turn(
            user_id="alice", content="next", conversation_id=42
        )
    assert session.added == []
    assert session.rollbacks == 1
```

- [ ] **Step 3: Run service tests and verify RED**

Run: `Set-Location backend; uv run pytest tests/test_chat_conversation_service.py -q`

Expected: FAIL because the service does not accept a lock factory or return lock ownership.

- [ ] **Step 4: Implement AcceptedCompletion and service ownership transfer**

```python
@dataclass(frozen=True, slots=True)
class AcceptedCompletion:
    turn: AcceptedUserTurn
    lock: Any
```

Acquire after new ID allocation or existing owner lookup and before mutation/message add. On any exception after acquisition, call `release_completion_lock(lock)` before re-raising.

- [ ] **Step 5: Run service tests and verify GREEN**

Run: `Set-Location backend; uv run pytest tests/test_chat_conversation_service.py tests/test_chat_completion_lock.py -q`

Expected: all tests PASS.

- [ ] **Step 6: Write failing registry lifecycle tests**

```python
@pytest.mark.asyncio
async def test_disconnect_keeps_lock_until_background_producer_finishes():
    subscriber = registry.start(
        producer_factory=producer_factory,
        turn=AcceptedUserTurn(1001, 2001, "hello"),
        completion_lock=lock,
        user_id="alice",
    )
    subscriber.detach()
    assert lock.release_calls == 0
    release_graph.set()
    await registry.shutdown()
    assert lock.release_calls == 1

@pytest.mark.asyncio
async def test_registry_releases_lock_when_producer_fails_or_is_cancelled():
    # producer exception and shutdown cancellation each release exactly once
```

- [ ] **Step 7: Run registry tests and verify RED**

Run: `Set-Location backend; uv run pytest tests/test_chat_completion_disconnect.py -q -k "lock"`

Expected: FAIL because Registry does not own or release the Redis lock.

- [ ] **Step 8: Wrap producer task with task-level finally**

```python
async def _run_locked_producer(self, producer, *, turn, user_id, completion_lock):
    try:
        await producer.run(turn=turn, user_id=user_id)
    finally:
        await release_completion_lock(completion_lock)
```

`start()` must create the task from `_run_locked_producer(producer, turn=turn, user_id=user_id, completion_lock=completion_lock)`, not directly from `producer.run(turn=turn, user_id=user_id)`.

- [ ] **Step 9: Write failing HTTP 409/503 and zero-Graph-call tests**

```python
@pytest.mark.parametrize(
    ("lock", "status_code"),
    [(FakeLock(acquired=False), 409), (FakeLock(acquire_error=OSError()), 503)],
)
@pytest.mark.asyncio
async def test_completion_lock_admission_failure_has_no_user_or_graph(lock, status_code):
    response = await client.post(
        "/api/v1/chat/completions",
        headers={"X-Mock-User-Id": "alice"},
        json={"conversation_id": "42", "content": "next"},
    )
    assert response.status_code == status_code
    assert session.added == []
    assert graph.state_configs == []
    assert graph.stream_invocations == []
```

- [ ] **Step 10: Map domain failures and protect pre-handoff failures**

Router behavior:

```python
except ConversationBusy as exc:
    raise AppException("conversation busy", status.HTTP_409_CONFLICT) from exc
except ConversationLockUnavailable as exc:
    raise AppException("conversation lock unavailable", status.HTTP_503_SERVICE_UNAVAILABLE) from exc
```

After acceptance, pass `accepted.lock` to Registry. If `registry.start()` raises before task ownership transfers, call `await release_completion_lock(accepted.lock)` and re-raise.

- [ ] **Step 11: Verify Task 2 GREEN**

Run: `Set-Location backend; uv run pytest tests/test_chat_conversation_service.py tests/test_chat_completion_api.py tests/test_chat_completion_disconnect.py tests/test_chat_completion_resume.py tests/test_chat_completion_producer.py -q`

Expected: all tests PASS, including old durability, resume, and disconnect behavior.

- [ ] **Step 12: Commit Task 2**

```powershell
git add backend/app/domains/chat/services/conversation.py backend/app/domains/chat/services/runtime.py backend/app/services/chat_api/router.py backend/tests/test_chat_conversation_service.py backend/tests/test_chat_completion_api.py backend/tests/test_chat_completion_disconnect.py
git commit -m "fix(chat): serialize conversation completions"
```

---

### Task 3: Chat Lifespan Redis Injection

**Files:**

- Modify: `backend/app/services/chat_api/deps.py`
- Modify: `backend/tests/test_chat_api_lifespan.py`

**Interfaces:**

- Adds: `ChatApiDeps.completion_lock_factory: Callable[[int], Any]`.
- Consumes: `create_redis_client(settings.redis_url)` and `partial(chat_completion_lock, redis_client=redis_client, expire_seconds=settings.chat_completion_lock_expire_seconds)`.

- [ ] **Step 1: Write failing lifespan order and injection test**

The test must assert Redis opens before serving, `completion_lock_factory(conversation_id=42)` receives the lifespan client and configured expiry, Registry shuts down before Redis closes, and app state is removed before external resources close.

- [ ] **Step 2: Run the lifespan test and verify RED**

Run: `Set-Location backend; uv run pytest tests/test_chat_api_lifespan.py -q`

Expected: FAIL because Chat lifespan does not create or expose Redis lock resources.

- [ ] **Step 3: Implement startup injection and LIFO cleanup**

```python
redis_client = create_redis_client(settings.redis_url)
stack.push_cleanup(redis_client.close)
completion_lock_factory = partial(
    chat_completion_lock,
    redis_client=redis_client,
    expire_seconds=settings.chat_completion_lock_expire_seconds,
)
```

Store the factory on `ChatApiDeps`; keep `producer_registry.shutdown` registered after Redis cleanup so LIFO waits for producers before closing Redis.

- [ ] **Step 4: Verify Task 3 GREEN**

Run: `Set-Location backend; uv run pytest tests/test_chat_api_lifespan.py tests/test_chat_completion_api.py -q`

Expected: all tests PASS and cleanup order is Registry → Redis → saver/database according to registration order.

- [ ] **Step 5: Commit Task 3**

```powershell
git add backend/app/services/chat_api/deps.py backend/tests/test_chat_api_lifespan.py
git commit -m "feat(chat): inject completion redis lock"
```

---

### Task 4: Prompt Contract Repair

**Files:**

- Modify: `backend/app/domains/chat/graph/business_understanding/prompt.py`
- Modify: `backend/tests/test_business_understanding_prompt.py`

**Interfaces:**

- Preserves: `BUSINESS_UNDERSTANDING_PROMPT_VERSION = "v1"`.
- Adds explicit text rules for unique context inheritance, non-invention, and valid BUSINESS/NON_BUSINESS/CLARIFY structured examples.

- [ ] **Step 1: Write the failing Prompt semantic test**

```python
def test_prompt_explicitly_defines_history_inheritance_and_all_route_examples():
    prompt = BUSINESS_UNDERSTANDING_SYSTEM_PROMPT
    for token in [
        "唯一确定", "按实际版呢", "继承", "不得臆造",
        '"route":"BUSINESS"',
        '"route":"NON_BUSINESS"',
        '"route":"CLARIFY"',
        '"clarification_question":"请提供运单号"',
    ]:
        assert token in prompt
```

- [ ] **Step 2: Run Prompt test and verify RED**

Run: `Set-Location backend; uv run pytest tests/test_business_understanding_prompt.py -q`

Expected: FAIL because the production Prompt lacks the explicit inheritance rule and examples.

- [ ] **Step 3: Add minimal explicit rules and three compact JSON examples**

Keep the existing taxonomy and boundaries. Add one multi-turn inheritance paragraph and one valid compact example per route; do not add RAG, SQL, confidence, retry, or new intent labels.

- [ ] **Step 4: Verify Task 4 GREEN**

Run: `Set-Location backend; uv run pytest tests/test_business_understanding_prompt.py tests/test_business_understanding_evaluation.py tests/test_business_understanding_models.py -q`

Expected: all tests PASS; evaluation remains explicitly deterministic and offline.

- [ ] **Step 5: Commit Task 4**

```powershell
git add backend/app/domains/chat/graph/business_understanding/prompt.py backend/tests/test_business_understanding_prompt.py
git commit -m "fix(chat): clarify business prompt context rules"
```

---

### Task 5: Real Redis Proof, Full Verification, and OpenSpec Closure

**Files:**

- Modify: `openspec/changes/add-business-understanding/tasks.md`
- Modify only if actual results change: the two implementation/evaluation documents under `docs/my-specs/`.

- [ ] **Step 1: Start required infrastructure**

Run: `docker compose up -d postgres redis`

Expected: both containers are running.

- [ ] **Step 2: Prove real Redis exclusion**

Run: `Set-Location backend; uv run pytest tests/test_chat_completion_lock.py -q -m integration`

Expected: first lock acquires, second same-conversation lock fails while held, then acquires after release; a different-conversation lock acquires independently.

- [ ] **Step 3: Run Chat and PostgreSQL verification**

```powershell
Set-Location backend
uv run pytest tests/test_business_understanding_models.py tests/test_business_understanding_prompt.py tests/test_business_understanding_evaluation.py tests/test_business_understanding_node.py tests/test_chat_graph.py tests/test_chat_graph_routing.py tests/test_chat_graph_clarification.py tests/test_chat_contracts.py tests/test_chat_sse_adapter.py tests/test_chat_completion_producer.py tests/test_chat_completion_resume.py tests/test_chat_completion_api.py tests/test_chat_completion_disconnect.py tests/test_chat_conversation_service.py tests/test_chat_completion_lock.py tests/test_chat_api_lifespan.py -q -m "not integration"
uv run pytest tests/test_chat_langgraph_postgres.py tests/test_chat_failure_consistency_postgres.py tests/test_business_understanding_postgres.py -q -m integration
```

Expected: both commands exit 0.

- [ ] **Step 4: Run all backend non-integration tests and deterministic evaluation**

```powershell
Set-Location backend
uv run pytest -q -m "not integration"
uv run pytest tests/test_business_understanding_evaluation.py -q -s
```

Expected: exit 0; evaluation output remains labeled `live_model=false`.

- [ ] **Step 5: Run frontend verification**

```powershell
Set-Location frontend
npm test
npm run lint
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 6: Run specification and formatting verification**

```powershell
Set-Location ..
openspec validate add-business-understanding --type change --strict
git diff --check
git status --short
```

Expected: OpenSpec valid, no whitespace errors, status only includes expected final-review files.

- [ ] **Step 7: Record actual evidence and complete Task 11 checkboxes**

Append exact commands, exit codes, counts, and deterministic/live-model distinction to Task 11. Mark a checkbox only after its evidence exists.

- [ ] **Step 8: Run a fresh final code review**

Review the final diff from `f132c5f5ff7ae9ede9233265377721ddb8b535e7` through HEAD for OpenSpec compliance, lock ownership/release, authorization concealment, resume correctness, security, and test quality. Resolve all Critical/Important findings or document an explicitly accepted deferral.

- [ ] **Step 9: Commit final evidence**

```powershell
git add openspec/changes/add-business-understanding/tasks.md docs/my-specs
git commit -m "test(chat): verify conversation completion lock"
```
