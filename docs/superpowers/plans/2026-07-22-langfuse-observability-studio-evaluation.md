# Langfuse Observability, Studio, and Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为现有 Chat LangGraph 增加 fail-open Langfuse tracing、复用唯一图拓扑的本地 Studio，以及基于现有 18 条用例的真实模型 Langfuse Dataset Experiment。

**Architecture:** FastAPI lifespan best-effort 创建一个具体的 Langfuse client/handler 资源，`CompletionProducer` 在应用级根 observation 中运行现有 Graph，并通过标准 callback 生成子 observations。Studio 只预绑定模型并调用现有 builder；评测 CLI 把本地 fixture 幂等同步到 Langfuse Dataset，直接执行真实 `business_understanding_node` 并用现有评分器生成五项 Scores。

**Tech Stack:** Python 3.11、FastAPI、LangGraph 1.2.9、LangChain 1.3.14、Langfuse Python SDK 4.14.1、LangGraph CLI 0.4.31、Pydantic Settings、pytest、uv、OpenSpec。

## Global Constraints

- 直接在当前 `feat/business-understanding` 分支实现，不创建新分支或 worktree。
- `builder.py` 是唯一图拓扑来源；不得复制节点、边或 `Command(goto)` 路由。
- Studio 不复用 FastAPI lifespan，不创建业务数据库、PostgreSQL saver、Redis、分布式锁、Registry、SSE 或 title model。
- 生产 Chat 与 Studio tracing 必须 fail-open；Langfuse 失败不得改变 Graph、checkpoint、Redis、业务数据库和 SSE 语义。
- 显式评测 CLI 必须 fail-fast；没有 Langfuse 配置或 Dataset Run 创建失败时返回非零退出码。
- 完整用户消息、Prompt、模型输入输出和结构化结果允许采集；不增加采样、脱敏或 tracing enabled 开关。
- 不追踪每个 SSE delta、Redis lock token、SQL、原始 checkpoint 或 title model。
- 首版评测固定 `max_concurrency=1`，不增加 LLM-as-a-Judge、CI 门禁、跨模型矩阵或生产 trace 回流。
- 运行依赖使用 `langfuse>=4.14.1,<5.0.0`；开发依赖使用 `langgraph-cli[inmem]>=0.4.31,<0.5.0`。
- Langfuse 官方 `CallbackHandler` 需要 LangChain 元包，运行依赖使用 `langchain>=1.3.14,<2.0.0`。
- 所有默认 pytest 使用 fake client/handler/model，不访问 Langfuse 或模型网络。

---

## File Structure

- Create `openspec/changes/add-langfuse-observability/`: 本次变更的 proposal、design、spec delta 与 tasks。
- Modify `backend/pyproject.toml`, `backend/uv.lock`: Langfuse 运行依赖和 Studio 开发依赖。
- Modify `backend/app/core/config.py`, `backend/.env.example`: Langfuse 标准连接配置，无启停开关。
- Create `backend/app/infrastructure/langfuse.py`: 具体的 Langfuse resources、根 observation、safe update/shutdown。
- Modify `backend/app/services/chat_api/deps.py`: lifespan best-effort 装配 Langfuse，保持正确关闭顺序。
- Modify `backend/app/services/chat_api/router.py`: 把可选 Langfuse resources 传给 Producer。
- Modify `backend/app/domains/chat/services/runtime.py`: completion 根 trace、attributes、Graph callback 和终态输出。
- Modify `backend/app/domains/chat/graph/nodes/business_understanding.py`: 抽出接收显式 model 的共享节点核心。
- Modify `backend/app/domains/chat/graph/nodes/llm.py`: 抽出接收显式 model 的共享节点核心。
- Modify `backend/app/domains/chat/graph/builder.py`: 增加可选 `bound_model`，但保留唯一拓扑。
- Modify `backend/app/infrastructure/llm.py`: 允许 Studio/Experiment 把 callback 交给 Chat model。
- Create `backend/app/entrypoints/studio_graph.py`, `backend/langgraph.json`: 极薄 Studio 入口。
- Create `backend/app/evaluation/__init__.py`, `backend/app/evaluation/business_understanding_langfuse.py`: Dataset 同步、真实 task、五维 evaluator 与 CLI。
- Create `backend/tests/test_langfuse_infrastructure.py`, `backend/tests/test_studio_graph.py`, `backend/tests/test_business_understanding_langfuse.py`: 新功能聚焦测试。
- Modify existing Chat/config/architecture tests and `backend/README.md`: 接线回归与使用说明。

### Task 1: OpenSpec 变更契约

**Files:**
- Create: `openspec/changes/add-langfuse-observability/proposal.md`
- Create: `openspec/changes/add-langfuse-observability/design.md`
- Create: `openspec/changes/add-langfuse-observability/specs/chat-langgraph-runtime/spec.md`
- Create: `openspec/changes/add-langfuse-observability/specs/business-understanding/spec.md`
- Create: `openspec/changes/add-langfuse-observability/tasks.md`

**Interfaces:**
- Consumes: confirmed design `docs/superpowers/specs/2026-07-22-langfuse-observability-studio-evaluation-design.md`.
- Produces: OpenSpec change `add-langfuse-observability` with testable tracing, Studio, and evaluation requirements.

- [ ] **Step 1: Create the OpenSpec artifacts**

The delta specs must state these observable requirements:

```markdown
### Requirement: Chat completion tracing is fail-open
The system SHALL trace each accepted Chat completion as one Langfuse root trace when Langfuse resources are available, and SHALL preserve the same completion result when Langfuse is unavailable.

#### Scenario: Langfuse is unavailable
- **WHEN** Langfuse initialization or delivery fails
- **THEN** the Chat completion SHALL continue without tracing

### Requirement: Studio reuses the production graph topology
The system SHALL expose a local Agent Server graph that binds a development model to the existing graph builder without loading FastAPI business resources.

### Requirement: Business understanding has a live Langfuse experiment
The system SHALL synchronize the 18 repository evaluation cases to a Langfuse Dataset and run the production business-understanding node with five deterministic scores.
```

- [ ] **Step 2: Validate the new change**

Run: `openspec validate add-langfuse-observability --strict`

Expected: exit 0 and strict validation passes.

- [ ] **Step 3: Commit the specification**

```powershell
git add openspec/changes/add-langfuse-observability
git commit -m "docs(openspec): specify langfuse observability"
```

### Task 2: Langfuse dependency, configuration, and fail-open resources

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Create: `backend/app/infrastructure/langfuse.py`
- Create: `backend/tests/test_langfuse_infrastructure.py`
- Modify: `backend/tests/test_document_config.py`

**Interfaces:**
- Consumes: `Settings` and standard Langfuse v4 constructors.
- Produces: `LangfuseResources`, `create_langfuse_resources(settings)`, `completion_trace(...)`, `safe_update_trace(...)`, and `shutdown_langfuse(resources)`.

- [ ] **Step 1: Add failing dependency and configuration tests**

```python
def test_langfuse_dependencies_are_available():
    assert importlib.util.find_spec("langfuse") is not None


def test_langfuse_settings_load_standard_environment_names(tmp_path):
    env_file = tmp_path / "backend.env"
    env_file.write_text(
        "\n".join([
            "LANGFUSE_PUBLIC_KEY=pk-test",
            "LANGFUSE_SECRET_KEY=sk-test",
            "LANGFUSE_BASE_URL=http://langfuse:3000",
            "LANGFUSE_TRACING_ENVIRONMENT=test",
            "LANGFUSE_RELEASE=release-1",
        ]),
        encoding="utf-8",
    )
    settings = config.create_settings(env_file=env_file)
    assert settings.langfuse_public_key == "pk-test"
    assert settings.langfuse_secret_key == "sk-test"
    assert settings.langfuse_base_url == "http://langfuse:3000"
    assert settings.langfuse_environment == "test"
    assert settings.langfuse_release == "release-1"
```

- [ ] **Step 2: Run tests to verify RED**

Run: `Set-Location backend; uv run pytest tests/test_document_config.py::test_langfuse_settings_load_standard_environment_names tests/test_langfuse_infrastructure.py -q`

Expected: FAIL because the dependency, settings, and infrastructure module do not exist.

- [ ] **Step 3: Add exact dependencies**

Run:

```powershell
Set-Location backend
uv add "langfuse>=4.14.1,<5.0.0"
uv add "langchain>=1.3.14,<2.0.0"
uv add --optional dev "langgraph-cli[inmem]>=0.4.31,<0.5.0"
```

Expected: `pyproject.toml` and `uv.lock` contain resolved compatible versions.

- [ ] **Step 4: Add Settings fields without an enable switch**

```python
langfuse_public_key: str | None = Field(
    default=None,
    validation_alias="LANGFUSE_PUBLIC_KEY",
    description="startup-only: Langfuse tracing client is created during process startup.",
)
langfuse_secret_key: str | None = Field(
    default=None,
    validation_alias="LANGFUSE_SECRET_KEY",
    description="startup-only: Langfuse tracing client is created during process startup.",
)
langfuse_base_url: str | None = Field(
    default=None,
    validation_alias="LANGFUSE_BASE_URL",
    description="startup-only: Langfuse endpoint is fixed for the process lifetime.",
)
langfuse_environment: str = Field(
    default="development",
    validation_alias="LANGFUSE_TRACING_ENVIRONMENT",
    description="startup-only: Langfuse trace environment is fixed for the process lifetime.",
)
langfuse_release: str | None = Field(
    default=None,
    validation_alias="LANGFUSE_RELEASE",
    description="startup-only: Langfuse release label is fixed for the process lifetime.",
)
```

Add all five fields to `STARTUP_ONLY_SETTINGS` and document their environment names in `.env.example`.

- [ ] **Step 5: Add fail-open resource tests**

```python
def test_create_langfuse_resources_returns_none_when_credentials_are_incomplete():
    settings = SimpleNamespace(langfuse_public_key=None, langfuse_secret_key=None)
    assert create_langfuse_resources(settings) is None


def test_create_langfuse_resources_builds_client_and_handler(monkeypatch):
    monkeypatch.setattr(module, "Langfuse", FakeLangfuse)
    monkeypatch.setattr(module, "CallbackHandler", FakeHandler)
    resources = create_langfuse_resources(complete_settings())
    assert resources.client.kwargs["base_url"] == "http://langfuse:3000"
    assert resources.handler.public_key == "pk-test"


def test_completion_trace_falls_back_when_span_enter_fails():
    resources = LangfuseResources(client=FailingEnterClient(), handler=object())
    with completion_trace(
        resources,
        input={"content": "raw"},
        session_id="1",
        user_id="user-1",
        metadata={"model": "test"},
        tags=["chat"],
    ) as span:
        assert span is None


async def test_shutdown_langfuse_swallows_shutdown_error():
    await shutdown_langfuse(
        LangfuseResources(client=FailingShutdownClient(), handler=object())
    )
```

- [ ] **Step 6: Implement the concrete Langfuse resource module**

```python
@dataclass(frozen=True, slots=True)
class LangfuseResources:
    client: Any
    handler: Any


def create_langfuse_resources(settings: Any) -> LangfuseResources | None:
    public_key = _clean(getattr(settings, "langfuse_public_key", None))
    secret_key = _clean(getattr(settings, "langfuse_secret_key", None))
    base_url = _clean(getattr(settings, "langfuse_base_url", None))
    if public_key is None or secret_key is None or base_url is None:
        logger.info("Langfuse tracing unavailable: incomplete configuration")
        return None
    try:
        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=base_url,
            environment=getattr(settings, "langfuse_environment", "development"),
            release=_clean(getattr(settings, "langfuse_release", None))
            or getattr(settings, "app_version", None),
        )
        return LangfuseResources(
            client=client,
            handler=CallbackHandler(public_key=public_key),
        )
    except Exception:
        logger.exception("Langfuse tracing initialization failed")
        return None
```

Implement `completion_trace()` as one narrow context manager. Its cleanup return value is intentionally ignored so Langfuse can never suppress a business exception:

```python
@contextmanager
def completion_trace(
    resources: LangfuseResources | None,
    *,
    input: dict[str, Any],
    session_id: str,
    user_id: str,
    metadata: dict[str, str],
    tags: list[str],
) -> Iterator[Any | None]:
    if resources is None:
        yield None
        return
    try:
        observation_context = resources.client.start_as_current_observation(
            as_type="span",
            name="chat-completion",
            input=input,
        )
        span = observation_context.__enter__()
    except Exception:
        logger.exception("Langfuse completion trace start failed")
        yield None
        return

    attributes_context = None
    try:
        attributes_context = propagate_attributes(
            session_id=session_id,
            user_id=user_id,
            metadata=metadata,
            tags=tags,
        )
        attributes_context.__enter__()
    except Exception:
        logger.exception("Langfuse attribute propagation failed")
        attributes_context = None

    try:
        yield span
    except BaseException as business_error:
        _safe_context_exit(attributes_context, business_error)
        _safe_context_exit(observation_context, business_error)
        raise
    else:
        _safe_context_exit(attributes_context, None)
        _safe_context_exit(observation_context, None)


def _safe_context_exit(context: Any | None, error: BaseException | None) -> None:
    if context is None:
        return
    try:
        context.__exit__(
            type(error) if error is not None else None,
            error,
            error.__traceback__ if error is not None else None,
        )
    except Exception:
        logger.exception("Langfuse context cleanup failed")


def safe_update_trace(span: Any | None, **kwargs: Any) -> None:
    if span is None:
        return
    try:
        span.update(**kwargs)
    except Exception:
        logger.exception("Langfuse trace update failed")


async def shutdown_langfuse(resources: LangfuseResources) -> None:
    try:
        await asyncio.to_thread(resources.client.shutdown)
    except Exception:
        logger.exception("Langfuse shutdown failed")
```

- [ ] **Step 7: Run focused tests to verify GREEN**

Run: `Set-Location backend; uv run pytest tests/test_document_config.py tests/test_langfuse_infrastructure.py -q`

Expected: all selected tests pass.

- [ ] **Step 8: Commit resources**

```powershell
git add backend/pyproject.toml backend/uv.lock backend/.env.example backend/app/core/config.py backend/app/infrastructure/langfuse.py backend/tests/test_document_config.py backend/tests/test_langfuse_infrastructure.py
git commit -m "feat(observability): add fail-open langfuse resources"
```

### Task 3: Production completion tracing

**Files:**
- Modify: `backend/app/services/chat_api/deps.py`
- Modify: `backend/app/services/chat_api/router.py`
- Modify: `backend/app/domains/chat/services/runtime.py`
- Modify: `backend/tests/test_chat_api_lifespan.py`
- Modify: `backend/tests/test_chat_completion_api.py`
- Modify: `backend/tests/test_chat_completion_producer.py`

**Interfaces:**
- Consumes: `LangfuseResources | None`, `completion_trace`, `safe_update_trace`, and `shutdown_langfuse` from Task 2.
- Produces: optional `ChatApiDeps.langfuse`, `CompletionProducer(..., langfuse=...)`, root trace output, propagated attributes, and Graph callbacks.

- [ ] **Step 1: Write failing lifespan and Router wiring tests**

```python
async def test_chat_lifespan_langfuse_is_fail_open_and_closes_after_registry(monkeypatch):
    monkeypatch.setattr(deps, "create_langfuse_resources", lambda settings: langfuse)
    monkeypatch.setattr(deps, "shutdown_langfuse", lambda resources: calls.append("langfuse_shutdown"))
    async with deps.application_lifespan_resources(application, settings):
        assert application.state.chat_deps.langfuse is langfuse
    assert calls[-5:] == [
        "registry_shutdown",
        "langfuse_shutdown",
        "redis_close",
        "saver_close",
        "database_close",
    ]
```

Extend the completion API test to assert the producer receives the same optional `chat_deps.langfuse` object.

- [ ] **Step 2: Run wiring tests to verify RED**

Run: `Set-Location backend; uv run pytest tests/test_chat_api_lifespan.py tests/test_chat_completion_api.py -q`

Expected: FAIL because `ChatApiDeps` and `CompletionProducer` have no Langfuse dependency.

- [ ] **Step 3: Wire lifespan and Router minimally**

```python
@dataclass(frozen=True, slots=True)
class ChatApiDeps:
    # existing fields unchanged
    langfuse: LangfuseResources | None


langfuse = create_langfuse_resources(settings)
if langfuse is not None:
    stack.push_cleanup(shutdown_langfuse, langfuse)


CompletionProducer(
    # existing arguments
    langfuse=chat_deps.langfuse,
)
```

Register Langfuse cleanup before registry cleanup so LIFO order is registry, Langfuse, Redis, saver, database.

- [ ] **Step 4: Write failing Producer trace tests**

```python
async def test_completion_producer_adds_langfuse_callback_and_updates_root_trace():
    trace = FakeTrace()
    resources = FakeResources(handler=handler, trace=trace)
    producer = make_producer(graph=graph, langfuse=resources)
    await producer.run(turn=turn, user_id="user-1")
    invocation = graph.invocations[0]
    assert invocation["config"]["callbacks"] == [handler]
    assert trace.start_input["content"] == turn.content
    assert trace.attributes["session_id"] == str(turn.conversation_id)
    assert trace.attributes["user_id"] == "user-1"
    assert trace.output == {
        "status": "completed",
        "content": "answer",
        "finish_reason": "stop",
    }


async def test_completion_business_error_is_not_replaced_by_trace_update_failure():
    producer = make_producer(graph=failing_graph, langfuse=failing_update_resources)
    await producer.run(turn=turn, user_id="user-1")
    assert publisher.events[-1][0] == "error"
```

- [ ] **Step 5: Run Producer tests to verify RED**

Run: `Set-Location backend; uv run pytest tests/test_chat_completion_producer.py -q`

Expected: FAIL because no root trace or callback is applied.

- [ ] **Step 6: Implement completion trace around the existing business flow**

```python
class CompletionProducer:
    def __init__(self, *, graph, model, session_factory, id_generator, publisher, langfuse=None):
        # existing assignments
        self._langfuse = langfuse

    async def run(self, *, turn: AcceptedUserTurn, user_id: str) -> None:
        with completion_trace(
            self._langfuse,
            input={
                "conversation_id": str(turn.conversation_id),
                "user_message_id": str(turn.user_message_id),
                "content": turn.content,
            },
            session_id=str(turn.conversation_id),
            user_id=user_id,
            metadata={"model": str(getattr(self._model, "model_name", "unknown"))},
            tags=["chat", "langgraph", "source:chat-api"],
        ) as trace:
            await self._run_completion(turn=turn, trace=trace)
```

Keep the existing metadata-first event order and single terminal event. In `_consume_graph_events`, add `config["callbacks"] = [self._langfuse.handler]` only when resources exist. Determine `input_mode` after `resolve_graph_input`; update trace metadata and final output via `safe_update_trace`.

- [ ] **Step 7: Run focused Chat tests to verify GREEN**

Run: `Set-Location backend; uv run pytest tests/test_chat_api_lifespan.py tests/test_chat_completion_api.py tests/test_chat_completion_producer.py tests/test_chat_completion_resume.py tests/test_chat_completion_disconnect.py -q`

Expected: all selected tests pass and existing terminal/SSE semantics are unchanged.

- [ ] **Step 8: Commit production tracing**

```powershell
git add backend/app/services/chat_api/deps.py backend/app/services/chat_api/router.py backend/app/domains/chat/services/runtime.py backend/tests/test_chat_api_lifespan.py backend/tests/test_chat_completion_api.py backend/tests/test_chat_completion_producer.py
git commit -m "feat(chat): trace completions with langfuse"
```

### Task 4: One graph builder and thin Studio adapter

**Files:**
- Modify: `backend/app/domains/chat/graph/nodes/business_understanding.py`
- Modify: `backend/app/domains/chat/graph/nodes/llm.py`
- Modify: `backend/app/domains/chat/graph/builder.py`
- Modify: `backend/app/infrastructure/llm.py`
- Create: `backend/app/entrypoints/studio_graph.py`
- Create: `backend/langgraph.json`
- Create: `backend/tests/test_studio_graph.py`
- Modify: `backend/tests/test_chat_graph.py`
- Modify: `backend/tests/test_target_architecture_layout.py`

**Interfaces:**
- Consumes: existing node behavior, `ChatRuntimeContext`, `create_chat_model`, and optional Langfuse handler.
- Produces: `build_chat_graph(*, bound_model: BaseChatModel | None = None)`, `invoke_business_understanding(state, *, model)`, `invoke_llm(state, *, model)`, and exported `studio_graph`.

- [ ] **Step 1: Write failing bound-model graph tests**

```python
async def test_bound_model_graph_runs_without_runtime_context():
    model = FakeStructuredModel(result=non_business_result())
    graph = build_chat_graph(bound_model=model).compile()
    result = await graph.ainvoke({"messages": [HumanMessage(content="你好")]})
    assert result["business_understanding"].route == BusinessRoute.NON_BUSINESS


def test_default_graph_keeps_chat_runtime_context_schema():
    graph = build_chat_graph()
    assert graph.context_schema is ChatRuntimeContext
```

- [ ] **Step 2: Run graph tests to verify RED**

Run: `Set-Location backend; uv run pytest tests/test_chat_graph.py -q`

Expected: FAIL because `build_chat_graph` has no `bound_model` argument.

- [ ] **Step 3: Extract model-explicit node cores and bind only in builder**

```python
async def invoke_business_understanding(
    state: ChatState,
    *,
    model: BaseChatModel,
) -> Command[Literal["llm", "business_boundary", "clarify"]]:
    structured_model = model.with_structured_output(BusinessUnderstandingResult)
    result = await structured_model.ainvoke(build_business_understanding_messages(state["messages"]))
    # existing target mapping and Command unchanged


async def business_understanding_node(state, runtime):
    return await invoke_business_understanding(state, model=runtime.context.model)
```

Apply the same pattern to `llm_node`. In `build_chat_graph`, use the original runtime nodes when `bound_model is None`; otherwise register `functools.partial()` of the model-explicit cores and omit `ChatRuntimeContext` from the Studio graph context schema. Keep every existing node name and edge declaration in this one function.

- [ ] **Step 4: Allow model construction callbacks without a new factory**

```python
def create_chat_model(settings: Any, *, model: str, callbacks: list[Any] | None = None) -> ChatOpenAI:
    kwargs: dict[str, Any] = {"api_key": api_key, "model": model}
    if callbacks:
        kwargs["callbacks"] = callbacks
    # existing base_url behavior unchanged
```

- [ ] **Step 5: Write failing Studio adapter tests**

```python
def test_studio_graph_uses_existing_builder_without_fastapi_resources(monkeypatch):
    monkeypatch.setattr(studio, "create_settings", lambda: settings)
    monkeypatch.setattr(studio, "create_chat_model", fake_create_model)
    monkeypatch.setattr(studio, "create_langfuse_resources", lambda settings: resources)
    graph = studio.create_studio_graph()
    assert builder_calls == [{"bound_model": model}]
    assert not imported("app.services.chat_api.deps")


def test_langgraph_json_exports_studio_graph():
    config = json.loads((BACKEND / "langgraph.json").read_text(encoding="utf-8"))
    assert config["graphs"] == {
        "chat": "./app/entrypoints/studio_graph.py:create_studio_graph"
    }
```

- [ ] **Step 6: Run Studio tests to verify RED**

Run: `Set-Location backend; uv run pytest tests/test_studio_graph.py tests/test_target_architecture_layout.py -q`

Expected: FAIL because the adapter and config do not exist.

- [ ] **Step 7: Implement the thin Studio graph factory**

```python
def create_studio_graph(config: RunnableConfig | None = None):
    settings = validate_chat_startup_settings(create_settings())
    langfuse = create_langfuse_resources(settings)
    callbacks = [langfuse.handler] if langfuse is not None else None
    model = create_chat_model(settings, model=settings.openai_model, callbacks=callbacks)
    return build_chat_graph(bound_model=model).compile()
```

Use this exact `backend/langgraph.json` shape:

```json
{
  "dependencies": ["."],
  "graphs": {
    "chat": "./app/entrypoints/studio_graph.py:create_studio_graph"
  },
  "env": ".env"
}
```

Do not import or call FastAPI lifespan resources. Agent Server owns development persistence.

- [ ] **Step 8: Run graph and Studio tests to verify GREEN**

Run: `Set-Location backend; uv run pytest tests/test_chat_graph.py tests/test_chat_graph_routing.py tests/test_chat_graph_clarification.py tests/test_studio_graph.py tests/test_target_architecture_layout.py -q`

Expected: all selected tests pass.

- [ ] **Step 9: Commit Studio support**

```powershell
git add backend/app/domains/chat/graph backend/app/infrastructure/llm.py backend/app/entrypoints/studio_graph.py backend/langgraph.json backend/tests/test_chat_graph.py backend/tests/test_studio_graph.py backend/tests/test_target_architecture_layout.py
git commit -m "feat(chat): add thin langgraph studio adapter"
```

### Task 5: Langfuse Dataset mapping and five-score evaluator

**Files:**
- Create: `backend/app/evaluation/__init__.py`
- Create: `backend/app/evaluation/business_understanding_langfuse.py`
- Create: `backend/tests/test_business_understanding_langfuse.py`

**Interfaces:**
- Consumes: `load_evaluation_cases()`, `score_evaluation_cases()`, `business_understanding_node`, `ChatRuntimeContext`, and Langfuse `Evaluation`.
- Produces: `dataset_item_id(case)`, `dataset_item_payload(case)`, `langfuse_evaluator(...)`, and `run_business_understanding_case(...)`.

- [ ] **Step 1: Write failing Dataset mapping tests**

```python
def test_dataset_mapping_is_stable_and_preserves_all_case_fields():
    case = load_evaluation_cases()[0]
    first = dataset_item_payload(case)
    second = dataset_item_payload(case)
    assert first == second
    assert first["id"] == dataset_item_id(case)
    assert first["input"] == {"messages": case.messages}
    assert first["expected_output"]["route"] == case.expected_route.value
    assert first["metadata"] == {
        "case_id": case.id,
        "category": case.category,
        "prompt_version": BUSINESS_UNDERSTANDING_PROMPT_VERSION,
    }


def test_all_eighteen_cases_have_unique_project_level_item_ids():
    ids = [dataset_item_id(case) for case in load_evaluation_cases()]
    assert len(ids) == len(set(ids)) == 18
```

- [ ] **Step 2: Write failing evaluator tests**

```python
def test_langfuse_evaluator_returns_five_numeric_scores():
    evaluations = langfuse_evaluator(
        input={"messages": case.messages},
        output=actual_result.model_dump(mode="json"),
        expected_output=expected_payload(case),
        metadata={"case_id": case.id, "category": case.category},
    )
    assert {evaluation.name for evaluation in evaluations} == {
        "route_accuracy",
        "intent_accuracy",
        "key_entity_recall",
        "clarification_accuracy",
        "schema_validity",
    }
    assert all(0 <= float(evaluation.value) <= 1 for evaluation in evaluations)
```

- [ ] **Step 3: Run mapping/evaluator tests to verify RED**

Run: `Set-Location backend; uv run pytest tests/test_business_understanding_langfuse.py -q`

Expected: FAIL because the evaluation adapter does not exist.

- [ ] **Step 4: Implement mapping and evaluator by reusing the existing scorer**

```python
DATASET_NAME = "ke-engine/business-understanding-v1"
DATASET_ITEM_NAMESPACE = UUID("a4b20d75-e25d-4c07-8930-d6954ee86318")


def dataset_item_id(case: EvaluationCase) -> str:
    return uuid5(DATASET_ITEM_NAMESPACE, f"{DATASET_NAME}:{case.id}").hex


def langfuse_evaluator(*, input, output, expected_output, metadata, **kwargs):
    case = evaluation_case_from_langfuse(input, expected_output, metadata)
    score = score_evaluation_cases(case, output)
    values = {
        "route_accuracy": _ratio(score.route),
        "intent_accuracy": _ratio(score.intent),
        "key_entity_recall": _ratio(score.key_entities, empty=1.0),
        "clarification_accuracy": _ratio(score.clarification),
        "schema_validity": _ratio(score.schema_validity),
    }
    return [
        Evaluation(
            name=name,
            value=value,
            comment=_score_comment(name, score),
            data_type="NUMERIC",
        )
        for name, value in values.items()
    ]
```

Do not duplicate the five matching rules; reconstruct `EvaluationCase` and call the existing scorer.

- [ ] **Step 5: Write failing real-node task test**

```python
async def test_experiment_task_invokes_the_real_business_understanding_node():
    item = FakeDatasetItem(input={"messages": case.messages})
    output = await run_business_understanding_case(item=item, model=model)
    assert output == expected_result.model_dump(mode="json")
    assert model.structured_invocations == [build_business_understanding_messages(messages)]
```

- [ ] **Step 6: Implement the task using the current node**

```python
async def run_business_understanding_case(*, item: Any, model: BaseChatModel) -> dict[str, Any]:
    messages = [_to_langchain_message(message) for message in item.input["messages"]]
    command = await business_understanding_node(
        {"messages": messages},
        Runtime(context=ChatRuntimeContext(model=model)),
    )
    result = command.update["business_understanding"]
    return result.model_dump(mode="json")
```

- [ ] **Step 7: Run evaluation adapter tests to verify GREEN**

Run: `Set-Location backend; uv run pytest tests/test_business_understanding_langfuse.py tests/test_business_understanding_evaluation.py tests/test_business_understanding_node.py -q`

Expected: all selected tests pass; the existing deterministic evaluator remains unchanged.

- [ ] **Step 8: Commit the Dataset/evaluator adapter**

```powershell
git add backend/app/evaluation backend/tests/test_business_understanding_langfuse.py
git commit -m "feat(evaluation): map business cases to langfuse"
```

### Task 6: Explicit live-model Experiment CLI and documentation

**Files:**
- Modify: `backend/app/evaluation/business_understanding_langfuse.py`
- Modify: `backend/tests/test_business_understanding_langfuse.py`
- Modify: `backend/README.md`

**Interfaces:**
- Consumes: Task 2 Langfuse configuration, Task 5 mapping/task/evaluator, `create_chat_model`, and Langfuse Dataset SDK.
- Produces: `sync_dataset(client, cases)`, `run_experiment(settings)`, `main()`, a non-zero failure contract, and runnable documentation.

- [ ] **Step 1: Write failing Dataset sync tests**

```python
def test_sync_dataset_creates_then_upserts_all_eighteen_items():
    client = FakeLangfuseClient(dataset_exists=False)
    dataset = sync_dataset(client, load_evaluation_cases())
    assert client.created_datasets == [DATASET_NAME]
    assert len(client.created_items) == 18
    assert all(item["dataset_name"] == DATASET_NAME for item in client.created_items)
    assert dataset is client.dataset


def test_sync_dataset_reuses_existing_dataset():
    client = FakeLangfuseClient(dataset_exists=True)
    sync_dataset(client, load_evaluation_cases())
    assert client.created_datasets == []
    assert len(client.created_items) == 18
```

- [ ] **Step 2: Write failing Experiment orchestration tests**

```python
def test_run_experiment_is_serial_and_prints_dataset_run_url(monkeypatch, capsys):
    result = FakeExperimentResult(dataset_run_url="http://langfuse/run/1")
    resources = fake_resources(result=result, auth_valid=True)
    run_experiment(settings(), resources=resources)
    client = resources.client
    call = client.dataset.experiment_calls[0]
    assert call["max_concurrency"] == 1
    assert call["metadata"]["live_model"] == "true"
    assert call["evaluators"] == [langfuse_evaluator]
    assert "http://langfuse/run/1" in capsys.readouterr().out


def test_main_returns_nonzero_when_langfuse_configuration_is_missing(monkeypatch):
    monkeypatch.setattr(module, "create_settings", incomplete_settings)
    assert main() == 1
```

- [ ] **Step 3: Run CLI tests to verify RED**

Run: `Set-Location backend; uv run pytest tests/test_business_understanding_langfuse.py -q`

Expected: FAIL because sync, orchestration, and CLI do not exist.

- [ ] **Step 4: Implement Dataset sync and explicit fail-fast CLI orchestration**

```python
def sync_dataset(client: Any, cases: list[EvaluationCase]) -> Any:
    try:
        client.get_dataset(DATASET_NAME)
    except NotFoundError:
        client.create_dataset(
            name=DATASET_NAME,
            description="18 labeled business-understanding regression cases",
            metadata={"source": "ke-engine", "prompt_version": BUSINESS_UNDERSTANDING_PROMPT_VERSION},
        )
    for case in cases:
        client.create_dataset_item(dataset_name=DATASET_NAME, **dataset_item_payload(case))
    return client.get_dataset(DATASET_NAME)


def run_experiment(
    settings: Settings,
    *,
    resources: LangfuseResources | None = None,
):
    resources = resources or create_langfuse_resources(settings)
    if resources is None:
        raise RuntimeError("Langfuse configuration is required for the experiment")
    client = resources.client
    try:
        if not client.auth_check():
            raise RuntimeError("Langfuse authentication failed")
        cases = load_evaluation_cases()
        dataset = sync_dataset(client, cases)
        model = create_chat_model(
            settings,
            model=settings.openai_model,
            callbacks=[resources.handler],
        )
        result = dataset.run_experiment(
            name="business-understanding-live-model",
            run_name=_default_run_name(),
            description="Production business-understanding node against 18 labeled cases",
            task=partial(run_business_understanding_case, model=model),
            evaluators=[langfuse_evaluator],
            max_concurrency=1,
            metadata={
                "model": settings.openai_model,
                "prompt_version": BUSINESS_UNDERSTANDING_PROMPT_VERSION,
                "app_version": settings.app_version,
                "live_model": "true",
            },
        )
        print(result.format())
        if result.dataset_run_url:
            print(result.dataset_run_url)
        return result
    finally:
        client.shutdown()
```

`main()` catches configuration/auth/network errors, logs one concise message, returns 1, and the module ends with `raise SystemExit(main())`. Do not downgrade this explicit command to no-op.

- [ ] **Step 5: Document exact development commands**

Add to `backend/README.md`:

```markdown
## Langfuse and LangGraph Studio

Set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`,
`LANGFUSE_TRACING_ENVIRONMENT`, and optionally `LANGFUSE_RELEASE` in `.env`.

- Start Chat API tracing: `uv run uvicorn app.entrypoints.chat_api:app --reload`
- Start local Agent Server/Studio: `uv run --extra dev langgraph dev`
- Run the 18-case live experiment:
  `uv run python -m app.evaluation.business_understanding_langfuse`

The Chat API and Studio are fail-open when Langfuse is unavailable. The explicit
experiment command fails with a non-zero exit code because otherwise no Dataset Run exists.
```

- [ ] **Step 6: Run evaluation tests to verify GREEN**

Run: `Set-Location backend; uv run pytest tests/test_business_understanding_langfuse.py tests/test_business_understanding_evaluation.py -q`

Expected: all selected tests pass without external network access.

- [ ] **Step 7: Commit the runnable Experiment**

```powershell
git add backend/app/evaluation/business_understanding_langfuse.py backend/tests/test_business_understanding_langfuse.py backend/README.md
git commit -m "feat(evaluation): run langfuse business experiment"
```

### Task 7: Regression, OpenSpec evidence, and final review

**Files:**
- Modify: `openspec/changes/add-langfuse-observability/tasks.md`
- Modify only if behavior changed: `docs/superpowers/specs/2026-07-22-langfuse-observability-studio-evaluation-design.md`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: verified change, complete evidence, clean worktree, and review-ready commits.

- [ ] **Step 1: Run all focused Langfuse, Graph, and Chat tests**

Run:

```powershell
Set-Location backend
uv run pytest tests/test_langfuse_infrastructure.py tests/test_studio_graph.py tests/test_business_understanding_langfuse.py tests/test_business_understanding_evaluation.py tests/test_business_understanding_node.py tests/test_chat_graph.py tests/test_chat_graph_routing.py tests/test_chat_graph_clarification.py tests/test_chat_api_lifespan.py tests/test_chat_completion_producer.py tests/test_chat_completion_resume.py tests/test_chat_completion_api.py tests/test_chat_completion_disconnect.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run the backend non-integration suite**

Run: `Set-Location backend; uv run pytest -q -m "not integration"`

Expected: exit 0; no default test contacts Langfuse or a model provider.

- [ ] **Step 3: Verify Studio configuration can be loaded**

Run: `Set-Location backend; uv run --extra dev langgraph dev --help`

Expected: exit 0 and the installed CLI exposes the `dev` command. Do not start a blocking server in automated verification.

- [ ] **Step 4: Validate OpenSpec and repository formatting**

Run:

```powershell
openspec validate add-langfuse-observability --strict
git diff --check
git status --short
```

Expected: OpenSpec validation passes, diff check is empty, and status contains only intended task evidence changes.

- [ ] **Step 5: Update OpenSpec task evidence**

Mark every implemented checkbox in `tasks.md` and record exact observed test counts, `live_model=false` for pytest, and that the real Langfuse/model run remains a manual command unless credentials are present.

- [ ] **Step 6: Commit verification evidence**

```powershell
git add openspec/changes/add-langfuse-observability/tasks.md
git commit -m "docs(openspec): record langfuse verification"
```

- [ ] **Step 7: Run final code review**

Review the complete diff from the design commit parent to `HEAD` for:

- business exceptions masked by telemetry cleanup;
- duplicate graph topology or FastAPI imports in Studio;
- accidental tracing of title model, SQL, Redis tokens, or SSE deltas;
- Experiment code that silently succeeds without a Dataset Run;
- evaluator rule duplication instead of reuse;
- untested network calls in default pytest;
- dependency or lock-file inconsistencies.

Fix any finding with a focused regression test before claiming completion.
