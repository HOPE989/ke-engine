# Business Understanding TDD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不实现 RAG/SQL 的前提下，为 ke-engine 增加可持久化、可流式交付、可中断恢复的 Business Understanding 节点，并稳定路由到 `BUSINESS`、`NON_BUSINESS` 或 `CLARIFY`。

**Architecture:** 使用现有 lifespan 注入的 Chat Model，通过 Pydantic structured output 一次完成意图识别与实体抽取；最新识别结果进入 `ChatState`，条件边连接现有 `llm`、确定性的 `business_boundary` 和 LangGraph `interrupt` 驱动的 `clarify`。Completion Producer 继续负责 metadata-first、ASSISTANT 先持久化后 completed，并在同一 conversation/thread 上使用 `Command(resume=user_content)` 恢复澄清。

**Tech Stack:** Python 3.11+、Pydantic 2、LangChain、LangGraph 1.2.9+、FastAPI、SQLAlchemy Async、PostgreSQL Checkpointer、pytest/pytest-asyncio、Next.js 15、TypeScript、Node Test Runner。

## Global Constraints

- 严格执行 `RED → Verify RED → GREEN → Verify GREEN → REFACTOR → Verify GREEN`；没有看到预期 RED 失败，不得写对应生产代码。
- 每个测试只验证一个行为；测试名称必须描述业务结果，禁止使用 `test1`、`works` 等宽泛名称。
- RED 必须是断言失败、导入缺失或未支持行为导致的失败；语法错误、fixture 错误、依赖未安装不算有效 RED。
- GREEN 只实现当前测试所需的最小行为；不得顺带实现 RAG、SQL、置信度、重试、`related`、`BusinessDomain` 或细粒度业务意图。
- 每轮 GREEN 后先运行当前测试文件，再运行本任务列出的回归集；Refactor 期间必须持续保持绿色。
- 测试优先使用真实 Pydantic 模型、真实 StateGraph 和内存 checkpointer；仅在模型、数据库或网络边界使用 fake，禁止只断言 mock 调用而不验证领域结果。
- 每次 Verify RED/Verify GREEN 都要在任务下记录命令、退出码和关键输出；禁止只勾选复选框而不保留证据。
- 普通回答的 `finish_reason` 保持 `stop`；只有受支持的 Business Understanding 澄清中断使用 `interrupt`。
- 公开 HTTP 请求不得增加 checkpoint ID、interrupt ID、LangGraph Command、route 或 intent 覆盖字段。
- 分类 JSON、`reasoning` 和 LangGraph 内部 Interrupt 对象不得进入公开 SSE 内容。
- BUSINESS 分支只返回确定性的开发阶段边界消息，不调用模型、RAG 或 SQL。
- 不新增业务表或数据库迁移；Graph runtime state 由 PostgreSQL checkpointer 持久化，用户可见消息仍以现有业务表为准。

## TDD Evidence Template

每个任务执行时，在对应步骤下追加如下证据，不修改原始验收条件：

```text
RED: <command>
Exit: <non-zero exit code>
Observed: <expected missing behavior>

GREEN: <command>
Exit: 0
Observed: <passed test count>

REGRESSION: <command>
Exit: 0
Observed: <passed test count>
```

---

## Task 1: Structured Business Understanding Contract

**Deliverable:** 一个禁止额外字段、可被 checkpoint 序列化、并强制跨字段不变量的结构化领域契约。

**Files:**

- Create: `backend/app/domains/chat/graph/business_understanding/__init__.py`
- Create: `backend/app/domains/chat/graph/business_understanding/models.py`
- Create: `backend/tests/test_business_understanding_models.py`

**Interfaces:**

- Produces: `BusinessRoute`, `BusinessIntent`, `BusinessEntities`, `BusinessUnderstandingResult`, `ClarificationInterruptPayload`。
- `BusinessUnderstandingResult` 字段固定为 `reasoning`, `route`, `intent`, `entities`, `clarification_question`。
- `ClarificationInterruptPayload` 公开给 Graph clarify node 与 SSE adapter 共用，固定 `kind="business_clarification"` 和非空 `question`。

- [x] **Step 1.1: RED — 写枚举值和字段集合测试**

```python
def test_business_understanding_contract_has_only_v1_routes_intents_and_fields():
    from app.domains.chat.graph.business_understanding import (
        BusinessEntities,
        BusinessIntent,
        BusinessRoute,
        BusinessUnderstandingResult,
    )

    assert {item.value for item in BusinessRoute} == {
        "BUSINESS", "NON_BUSINESS", "CLARIFY"
    }
    assert {item.value for item in BusinessIntent} == {
        "POLICY_RULE_QA",
        "TRANSPORT_OPERATION_QA",
        "COAL_SALES_QA",
        "PROFESSIONAL_KNOWLEDGE_QA",
        "BUSINESS_DATA_QUERY",
        "OTHER_BUSINESS",
    }
    assert set(BusinessUnderstandingResult.model_fields) == {
        "reasoning", "route", "intent", "entities", "clarification_question"
    }
    assert set(BusinessEntities.model_fields) == {
        "operation_plan_no", "train_no", "formation_no", "contract_no",
        "document_type", "document_no", "customer", "supplier", "coal_type",
        "departure_station", "arrival_station", "railway_section", "time_range",
        "data_version", "metric_name", "exception_description",
    }
    assert {"related", "confidence", "business_domain"}.isdisjoint(
        BusinessUnderstandingResult.model_fields
    )
```

- [x] **Step 1.2: Verify RED — 证明契约尚不存在**

Run: `Set-Location backend; uv run pytest tests/test_business_understanding_models.py -q`

Expected: FAIL during collection with `ModuleNotFoundError` for `business_understanding`；若测试直接 PASS，停止并检查是否已有未纳入计划的实现。

```text
RED: Set-Location backend; uv run pytest tests/test_business_understanding_models.py -q
Exit: 1
Observed: 6 failed，均为缺少 business_understanding 包导致的 ModuleNotFoundError；新增 payload 空白校验 RED 为 1 failed, 3 passed, 6 deselected，纯空白 question 未抛 ValidationError。
```

- [x] **Step 1.3: RED — 写 BUSINESS/NON_BUSINESS/CLARIFY 跨字段验证测试**

```python
@pytest.mark.parametrize(
    "payload",
    [
        {"reasoning": "业务请求缺少意图", "route": "BUSINESS", "intent": None,
         "entities": {}, "clarification_question": None},
        {"reasoning": "非业务不得保留意图", "route": "NON_BUSINESS",
         "intent": "OTHER_BUSINESS", "entities": {}, "clarification_question": None},
        {"reasoning": "澄清问题不能为空", "route": "CLARIFY",
         "intent": "BUSINESS_DATA_QUERY", "entities": {},
         "clarification_question": "   "},
    ],
)
def test_business_understanding_rejects_inconsistent_cross_field_payload(payload):
    from app.domains.chat.graph.business_understanding import BusinessUnderstandingResult

    with pytest.raises(ValidationError):
        BusinessUnderstandingResult.model_validate(payload)


def test_business_understanding_rejects_unknown_intent_and_extra_legacy_fields():
    from app.domains.chat.graph.business_understanding import BusinessUnderstandingResult

    base = {
        "reasoning": "具体业务查询",
        "route": "BUSINESS",
        "intent": "PLAN_QUERY",
        "entities": {},
        "clarification_question": None,
        "related": True,
    }
    with pytest.raises(ValidationError):
        BusinessUnderstandingResult.model_validate(base)
```

- [x] **Step 1.4: GREEN — 实现最小 Pydantic 契约**

```python
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BusinessRoute(StrEnum):
    BUSINESS = "BUSINESS"
    NON_BUSINESS = "NON_BUSINESS"
    CLARIFY = "CLARIFY"


class BusinessIntent(StrEnum):
    POLICY_RULE_QA = "POLICY_RULE_QA"
    TRANSPORT_OPERATION_QA = "TRANSPORT_OPERATION_QA"
    COAL_SALES_QA = "COAL_SALES_QA"
    PROFESSIONAL_KNOWLEDGE_QA = "PROFESSIONAL_KNOWLEDGE_QA"
    BUSINESS_DATA_QUERY = "BUSINESS_DATA_QUERY"
    OTHER_BUSINESS = "OTHER_BUSINESS"


class BusinessEntities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_plan_no: str | None = None
    train_no: str | None = None
    formation_no: str | None = None
    contract_no: str | None = None
    document_type: str | None = None
    document_no: str | None = None
    customer: str | None = None
    supplier: str | None = None
    coal_type: str | None = None
    departure_station: str | None = None
    arrival_station: str | None = None
    railway_section: str | None = None
    time_range: str | None = None
    data_version: str | None = None
    metric_name: str | None = None
    exception_description: str | None = None


class BusinessUnderstandingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasoning: str = Field(min_length=1)
    route: BusinessRoute
    intent: BusinessIntent | None = None
    entities: BusinessEntities = Field(default_factory=BusinessEntities)
    clarification_question: str | None = None

    @model_validator(mode="after")
    def validate_route_contract(self) -> Self:
        if self.route is BusinessRoute.BUSINESS:
            if self.intent is None or self.clarification_question is not None:
                raise ValueError("BUSINESS requires intent and forbids clarification")
        elif self.route is BusinessRoute.NON_BUSINESS:
            if self.intent is not None or self.clarification_question is not None:
                raise ValueError("NON_BUSINESS forbids intent and clarification")
        elif not (self.clarification_question and self.clarification_question.strip()):
            raise ValueError("CLARIFY requires a non-blank question")
        return self


class ClarificationInterruptPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["business_clarification"] = "business_clarification"
    question: str = Field(min_length=1)
```

- [x] **Step 1.5: Verify GREEN — 运行契约测试与序列化回归**

Run: `Set-Location backend; uv run pytest tests/test_business_understanding_models.py tests/test_chat_contracts.py -q`

Expected: PASS；新增一个 `dumped = result.model_dump(mode="json")`、`restored = BusinessUnderstandingResult.model_validate(dumped)` 的 round-trip 测试，证明 checkpoint-safe 数据可还原。

```text
GREEN: Set-Location backend; uv run pytest tests/test_business_understanding_models.py tests/test_chat_contracts.py -q
Exit: 0
Observed: 24 passed in 0.42s（控制器独立复跑）。

REGRESSION: Set-Location backend; uv run pytest tests/test_business_understanding_models.py tests/test_chat_contracts.py -q; git diff --check fde1154..HEAD
Exit: 0
Observed: 24 passed；git diff --check 无输出。
```

- [x] **Step 1.6: REFACTOR — 仅整理导出和命名后保持绿色**

在 `business_understanding/__init__.py` 显式导出五个契约类型，不导出 Pydantic 内部辅助函数；再次运行 Step 1.5。

- [x] **Step 1.7: Commit**

```powershell
git add backend/app/domains/chat/graph/business_understanding backend/tests/test_business_understanding_models.py
git commit -m "feat(chat): add business understanding contract"
```

---

## Task 2: Versioned Prompt and Deterministic Evaluation Dataset

**Deliverable:** 一个可版本追踪的铁路/煤炭 Prompt，以及覆盖边界负例、多轮省略、实体和澄清的离线标注集；本任务不调用在线模型。

**Files:**

- Create: `backend/app/domains/chat/graph/business_understanding/prompt.py`
- Create: `backend/app/domains/chat/graph/business_understanding/evaluation.py`
- Create: `backend/tests/fixtures/business_understanding_cases.json`
- Create: `backend/tests/test_business_understanding_prompt.py`
- Create: `backend/tests/test_business_understanding_evaluation.py`

**Interfaces:**

- Produces: `BUSINESS_UNDERSTANDING_PROMPT_VERSION = "v1"`。
- Produces: `build_business_understanding_messages(messages: Sequence[BaseMessage]) -> list[BaseMessage]`。
- Produces: `EvaluationCase` 和 `score_evaluation_cases(expected, actual)`；评分维度固定为 route、intent、key entities、clarification、schema validity。

- [x] **Step 2.1: RED — 写 Prompt 内容与历史传递测试**

```python
def test_business_understanding_prompt_is_versioned_and_contains_all_control_rules():
    from app.domains.chat.graph.business_understanding.prompt import (
        BUSINESS_UNDERSTANDING_PROMPT_VERSION,
        BUSINESS_UNDERSTANDING_SYSTEM_PROMPT,
    )

    assert BUSINESS_UNDERSTANDING_PROMPT_VERSION == "v1"
    for token in [
        "BUSINESS", "NON_BUSINESS", "CLARIFY", "POLICY_RULE_QA",
        "TRANSPORT_OPERATION_QA", "COAL_SALES_QA",
        "PROFESSIONAL_KNOWLEDGE_QA", "BUSINESS_DATA_QUERY", "OTHER_BUSINESS",
        "高铁客票", "运单", "货票", "运行计划", "编组", "实际版", "模拟版",
    ]:
        assert token in BUSINESS_UNDERSTANDING_SYSTEM_PROMPT
    for forbidden in ["related", "BusinessDomain", "confidence"]:
        assert forbidden not in BUSINESS_UNDERSTANDING_SYSTEM_PROMPT


def test_prompt_builder_keeps_checkpoint_history_after_single_system_message():
    history = [HumanMessage(content="查神木站模拟装车计划"),
               AIMessage(content="开发阶段边界响应"),
               HumanMessage(content="按实际版呢")]
    built = build_business_understanding_messages(history)

    assert isinstance(built[0], SystemMessage)
    assert built[1:] == history
```

- [x] **Step 2.2: Verify RED — 证明 Prompt 模块尚不存在**

Run: `Set-Location backend; uv run pytest tests/test_business_understanding_prompt.py -q`

Expected: FAIL with missing `prompt` module or missing versioned constant。

```text
RED: Set-Location backend; uv run pytest tests/test_business_understanding_prompt.py -q
Exit: 1
Observed: 2 failed，缺少 business_understanding.prompt 模块。
```

- [x] **Step 2.3: GREEN — 增加最小版本化 Prompt 构造器**

`BUSINESS_UNDERSTANDING_SYSTEM_PROMPT` 必须把以下规则直接写入常量，不能把规则留给执行者二次推断：

```text
角色：铁路运输、煤炭运输、煤炭销售和企业知识场景的 Business Understanding 分类器。
任务：结合完整消息历史，一次输出 route、intent、entities、clarification_question 和简短 reasoning。
边界：公众高铁/客票/旅游问答属于 NON_BUSINESS；企业货运、运行计划、编组、货单、运单、货票属于业务场景。
知识与数据：询问概念、制度、规程或流程使用知识类 intent；携带或要求具体编号、状态、数量、统计或实际/模拟对比使用 BUSINESS_DATA_QUERY。
澄清：只有继续执行所必需的信息既不在当前输入也不在历史中时才 CLARIFY；一次只问最小缺失项。
禁止：不得输出 related、BusinessDomain、confidence；不得伪造编号、车站、时间或数据版本。
输出：仅返回结构化契约允许的字段，不输出 Markdown。
```

构造器只添加一个 `SystemMessage`，随后原样附加 checkpoint messages，不截断、不重排、不把历史拼成一个字符串。

- [x] **Step 2.4: RED — 写评测集覆盖测试**

```python
def test_evaluation_dataset_covers_required_boundary_groups():
    cases = load_evaluation_cases()
    categories = {case.category for case in cases}
    assert {
        "public_passenger_negative",
        "freight_document_knowledge",
        "freight_document_lookup",
        "policy_vs_professional",
        "transport_vs_coal_sales",
        "multi_turn_ellipsis",
        "focused_clarification",
        "optional_entity_no_clarification",
        "unsupported_schema",
    } <= categories
    assert all(case.expected_key_entities.keys() <= BusinessEntities.model_fields.keys()
               for case in cases)
```

- [x] **Step 2.5: GREEN — 建立离线 JSON 标注集**

每个 case 固定包含 `id`, `category`, `messages`, `expected_route`, `expected_intent`, `expected_key_entities`, `expected_clarification_contains`。至少写入以下代表案例，并为每个分类补足一条独立用例：

```json
[
  {"id":"passenger-refund","category":"public_passenger_negative","messages":[{"role":"user","content":"高铁票怎么退票"}],"expected_route":"NON_BUSINESS","expected_intent":null,"expected_key_entities":{},"expected_clarification_contains":null},
  {"id":"waybill-knowledge","category":"freight_document_knowledge","messages":[{"role":"user","content":"铁路货运运单一般包含哪些信息"}],"expected_route":"BUSINESS","expected_intent":"TRANSPORT_OPERATION_QA","expected_key_entities":{"document_type":"运单"},"expected_clarification_contains":null},
  {"id":"waybill-lookup","category":"freight_document_lookup","messages":[{"role":"user","content":"查一下运单YD2026001现在到哪了"}],"expected_route":"BUSINESS","expected_intent":"BUSINESS_DATA_QUERY","expected_key_entities":{"document_type":"运单","document_no":"YD2026001"},"expected_clarification_contains":null},
  {"id":"missing-waybill","category":"focused_clarification","messages":[{"role":"user","content":"查一下我的运单"}],"expected_route":"CLARIFY","expected_intent":"BUSINESS_DATA_QUERY","expected_key_entities":{"document_type":"运单"},"expected_clarification_contains":"运单号"},
  {"id":"actual-followup","category":"multi_turn_ellipsis","messages":[{"role":"user","content":"查神木站本月模拟装车计划"},{"role":"assistant","content":"开发阶段暂不执行业务查询"},{"role":"user","content":"按实际版呢"}],"expected_route":"BUSINESS","expected_intent":"BUSINESS_DATA_QUERY","expected_key_entities":{"departure_station":"神木站","time_range":"本月","data_version":"实际版","metric_name":"装车计划"},"expected_clarification_contains":null}
]
```

- [x] **Step 2.6: RED/GREEN — 为分维度评分写纯函数测试并实现最小评分器**

先写一个包含 route 正确、intent 错误、两个实体命中一个、澄清正确、schema 有效的测试，断言结果分别为 `1/1`, `0/1`, `1/2`, `1/1`, `1/1`；运行确认因评分器不存在而 RED，再实现只比较显式标注 key entities 的纯函数。

Run RED/GREEN: `Set-Location backend; uv run pytest tests/test_business_understanding_evaluation.py -q`

```text
RED: Set-Location backend; uv run pytest tests/test_business_understanding_evaluation.py -q
Exit: 1
Observed: 初次缺少 evaluation 模块；评分器阶段缺少 score_evaluation_cases；覆盖强化阶段准确报告 optional_entity_no_clarification 与 unsupported_schema 各仅一个样例。

GREEN: Set-Location backend; uv run pytest tests/test_business_understanding_evaluation.py -q
Exit: 0
Observed: 2 passed；九个 required categories 均至少有两个独立 case，五个评分维度分别断言。
```

- [x] **Step 2.7: Verify GREEN — 运行 Prompt、数据集和契约回归**

Run: `Set-Location backend; uv run pytest tests/test_business_understanding_prompt.py tests/test_business_understanding_evaluation.py tests/test_business_understanding_models.py -q`

Expected: PASS，且测试不发起网络请求、不读取模型密钥。

```text
REGRESSION: Set-Location backend; uv run pytest tests/test_business_understanding_prompt.py tests/test_business_understanding_evaluation.py tests/test_business_understanding_models.py -q
Exit: 0
Observed: 14 passed in 0.44s（控制器独立复跑）；新增代码静态只读取本地 JSON fixture，无网络、模型或密钥依赖。
```

- [x] **Step 2.8: Commit**

```powershell
git add backend/app/domains/chat/graph/business_understanding backend/tests/fixtures/business_understanding_cases.json backend/tests/test_business_understanding_prompt.py backend/tests/test_business_understanding_evaluation.py
git commit -m "feat(chat): add business understanding prompt cases"
```

---

## Task 3: Business Understanding Node and Checkpoint State

**Deliverable:** 节点从 `ChatRuntimeContext.model` 派生 structured runnable，传入完整消息历史，并只把验证后的最新结果写入 state。

**Files:**

- Modify: `backend/app/domains/chat/graph/state.py`
- Create: `backend/app/domains/chat/graph/nodes/business_understanding.py`
- Modify: `backend/app/domains/chat/graph/nodes/__init__.py`
- Modify: `backend/app/domains/chat/graph/__init__.py`
- Create: `backend/tests/test_business_understanding_node.py`

**Interfaces:**

- Produces: `async business_understanding_node(state: ChatState, runtime: Runtime[ChatRuntimeContext]) -> dict[str, BusinessUnderstandingResult]`。
- `ChatState.business_understanding` 保存最新 `BusinessUnderstandingResult`，model/settings/pool/prompt loader 仍只存在于 runtime/module。

- [x] **Step 3.1: RED — 写 fake structured model 的成功路径测试**

```python
class FakeStructuredRunnable:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return self.result


class FakeStructuredModel:
    def __init__(self, runnable):
        self.runnable = runnable
        self.schemas = []

    def with_structured_output(self, schema):
        self.schemas.append(schema)
        return self.runnable


@pytest.mark.asyncio
async def test_business_understanding_node_uses_injected_structured_model_and_history():
    result = BusinessUnderstandingResult.model_validate({
        "reasoning": "提供了具体运单号", "route": "BUSINESS",
        "intent": "BUSINESS_DATA_QUERY",
        "entities": {"document_type": "运单", "document_no": "YD2026001"},
        "clarification_question": None,
    })
    runnable = FakeStructuredRunnable(result)
    model = FakeStructuredModel(runnable)
    history = [HumanMessage(content="查运单YD2026001")]

    update = await business_understanding_node(
        {"messages": history}, Runtime(context=ChatRuntimeContext(model=model))
    )

    assert model.schemas == [BusinessUnderstandingResult]
    assert runnable.calls[0][1:] == history
    assert update == {"business_understanding": result}
```

- [x] **Step 3.2: Verify RED — 证明节点尚不存在**

Run: `Set-Location backend; uv run pytest tests/test_business_understanding_node.py -q`

Expected: FAIL with missing node import。

```text
RED: Set-Location backend; uv run pytest tests/test_business_understanding_node.py -q
Exit: 2
Observed: collection 因缺少 graph.nodes.business_understanding 模块失败；失败来自目标能力缺失。
```

- [x] **Step 3.3: RED — 写无重试、无部分 state、无基础设施构造测试**

让 fake structured runnable 的唯一一次 `ainvoke` 抛出 `ValidationError` 或 `RuntimeError`；断言异常原样传播且调用次数为 1。导入测试继续 monkeypatch `create_chat_model/get_settings/get_session_factory` 为抛错函数，证明模块导入不会触发它们。

- [x] **Step 3.4: GREEN — 实现最小 state 字段和节点**

```python
async def business_understanding_node(state, runtime):
    structured_model = runtime.context.model.with_structured_output(
        BusinessUnderstandingResult
    )
    result = await structured_model.ainvoke(
        build_business_understanding_messages(state["messages"])
    )
    return {"business_understanding": result}
```

`ChatState` 只增加类型化 `business_understanding` 字段；不把 structured runnable 缓存到 state，不捕获异常做 route fallback，不设置 retry policy。

- [x] **Step 3.5: Verify GREEN — 运行节点和原 Graph 单元回归**

Run: `Set-Location backend; uv run pytest tests/test_business_understanding_node.py tests/test_chat_graph.py -q`

Expected: 新节点测试 PASS；旧拓扑断言会在 Task 4 才被替换，因此本任务不得提前改 builder。

```text
GREEN: Set-Location backend; uv run pytest tests/test_business_understanding_node.py -q
Exit: 0
Observed: 5 passed。

REGRESSION: Set-Location backend; uv run pytest tests/test_business_understanding_node.py tests/test_chat_graph.py -q
Exit: 0
Observed: 10 passed in 1.28s（控制器独立复跑）；builder 未修改，旧拓扑仍通过。计划文字中的 Task 4 已按用户裁定解释为 Task 5。
```

- [x] **Step 3.6: Commit**

```powershell
git add backend/app/domains/chat/graph backend/tests/test_business_understanding_node.py
git commit -m "feat(chat): add business understanding node"
```

---

## Task 4: Route Decision and BUSINESS Boundary Primitives

**Deliverable:** 提供可独立单测的条件路由函数与确定性 BUSINESS 边界节点；本任务不修改 builder，避免在 clarify 尚未实现时产生不可编译的中间提交。

**Files:**

- Create: `backend/app/domains/chat/graph/routing.py`
- Create: `backend/app/domains/chat/graph/nodes/business_boundary.py`
- Modify: `backend/app/domains/chat/graph/__init__.py`
- Create: `backend/tests/test_chat_graph_routing.py`

**Interfaces:**

- Produces constants: `BUSINESS_UNDERSTANDING_NODE`, `BUSINESS_BOUNDARY_NODE`, `CLARIFY_NODE`, `LLM_NODE`。
- Produces: `route_business_understanding(state) -> Literal["llm", "business_boundary", "clarify"]`。
- Produces: `BUSINESS_BOUNDARY_MESSAGE`，其内容明确表示已识别业务请求但当前阶段尚未连接业务检索。

- [x] **Step 4.1: RED — 写三种 route 到节点名的纯函数测试**

分别构造 BUSINESS、NON_BUSINESS、CLARIFY 的合法 `BusinessUnderstandingResult` 放入 state，断言 `route_business_understanding` 精确返回 `business_boundary`、`llm`、`clarify`；缺少结果时必须抛出 `KeyError`，不得猜测默认 route。

Run: `Set-Location backend; uv run pytest tests/test_chat_graph_routing.py::test_route_business_understanding_maps_each_route_to_one_node -q`

Expected: FAIL，因为 routing 模块尚不存在。

- [x] **Step 4.2: RED — 写 BUSINESS 边界节点隔离测试**

直接调用 `business_boundary_node`，断言只返回一条内容等于 `BUSINESS_BOUNDARY_MESSAGE` 的 AIMessage；函数签名不接收 runtime，因此不可能调用 model。再做 import 扫描，断言模块不导入 RAG、SQLAlchemy、repository 或 settings。

- [x] **Step 4.3: Verify RED — 同时运行 router 与边界测试**

Run: `Set-Location backend; uv run pytest tests/test_chat_graph_routing.py -q`

Expected: FAIL only because routing/boundary production symbols are missing。

```text
RED: Set-Location backend; uv run pytest tests/test_chat_graph_routing.py -q
Exit: 1
Observed: 6 failures，仅因 routing 与 business_boundary 生产模块缺失。
```

- [x] **Step 4.4: GREEN — 实现 router 和边界节点**

```python
def route_business_understanding(state: ChatState) -> str:
    result = state["business_understanding"]
    return {
        BusinessRoute.NON_BUSINESS: LLM_NODE,
        BusinessRoute.BUSINESS: BUSINESS_BOUNDARY_NODE,
        BusinessRoute.CLARIFY: CLARIFY_NODE,
    }[result.route]


def business_boundary_node(state: ChatState) -> dict[str, list[AIMessage]]:
    return {"messages": [AIMessage(content=BUSINESS_BOUNDARY_MESSAGE)]}
```

本任务不改 builder；现有 `START -> llm -> END` 在 Task 5 完成前继续可运行。边界消息定义为模块常量，测试与后续 Graph 共用同一常量，避免复制中文文本。

- [x] **Step 4.5: Verify GREEN — 运行 primitives 与旧 Graph 回归**

Run: `Set-Location backend; uv run pytest tests/test_chat_graph.py tests/test_chat_graph_routing.py -q`

Expected: router/boundary primitives PASS，现有 Graph 仍保持 `START -> llm -> END` 且原 MessagesState reducer 测试 PASS。

```text
GREEN: Set-Location backend; uv run pytest tests/test_chat_graph.py tests/test_chat_graph_routing.py -q
Exit: 0
Observed: 11 passed in 1.34s（控制器独立复跑）；三路映射、缺失 state、边界消息和旧 Graph 均通过。

REGRESSION: Set-Location backend; uv run pytest -q
Exit: 1
Observed: 517 passed, 3 skipped, 2 PostgreSQL integration failures；失败均因本地 127.0.0.1:5432 未启动，留至 Task 10 基础设施门禁。
```

- [x] **Step 4.6: Commit**

```powershell
git add backend/app/domains/chat/graph backend/tests/test_chat_graph_routing.py
git commit -m "feat(chat): add business route primitives"
```

---

## Task 5: CLARIFY Interrupt and Graph Resume

**Deliverable:** 一次性把 builder 升级为完整三路拓扑；CLARIFY 用真实 LangGraph interrupt 挂起，收到 resume 值后把澄清问题和用户回答加入 message state，再回到 Business Understanding 重新识别。

**Files:**

- Create: `backend/app/domains/chat/graph/nodes/clarify.py`
- Modify: `backend/app/domains/chat/graph/builder.py`
- Modify: `backend/app/domains/chat/graph/nodes/__init__.py`
- Modify: `backend/tests/test_chat_graph.py`
- Modify: `backend/tests/test_chat_graph_routing.py`
- Create: `backend/tests/test_chat_graph_clarification.py`

**Interfaces:**

- Produces: `clarify_node(state: ChatState) -> dict[str, list[BaseMessage]]`。
- Interrupt value 必须等于 `ClarificationInterruptPayload.model_dump(mode="json")`。
- Resume 后返回 `[AIMessage(question), HumanMessage(resume_value)]`，静态边为 `clarify -> business_understanding`。

- [x] **Step 5.1: RED — 先替换稳定拓扑断言**

在 `test_chat_graph.py` 中将旧 `START -> llm -> END` 断言改为完整节点/边/无 retry 的断言；条件边可视化分支必须包含 `llm`、`business_boundary`、`clarify`，且四个节点 retry policy 均为 `None`。

Run: `Set-Location backend; uv run pytest tests/test_chat_graph.py::test_chat_graph_has_business_understanding_routes_and_no_retry_policy -q`

Expected: FAIL，因为 builder 仍是旧拓扑。

```text
RED: Set-Location backend; uv run pytest tests/test_chat_graph.py::test_chat_graph_has_business_understanding_routes_and_no_retry_policy -q
Exit: 1
Observed: 旧图仅有 START -> llm -> END，缺少完整 Business Understanding 分支。
```

- [x] **Step 5.2: RED — 写 NON_BUSINESS 与 BUSINESS 真实 Graph 路径测试**

NON_BUSINESS 使用顺序 fake model：structured 调用返回 NON_BUSINESS，普通调用返回 `AIMessage("通用回答")`，断言两类调用各一次。BUSINESS 的普通 `ainvoke` 若被调用立即抛 `AssertionError`，断言最终消息等于 `BUSINESS_BOUNDARY_MESSAGE`，分类 reasoning 未进入 messages。

- [x] **Step 5.3: RED — 写首次 CLARIFY 挂起测试**

使用 `InMemorySaver` 编译真实 Graph，thread ID 固定为测试值；fake structured model 返回 CLARIFY。调用 `graph.ainvoke({"messages": [HumanMessage(content="查一下我的运单")]}, config, context=runtime_context)` 后读取 `graph.aget_state(config)`，断言：

```python
assert snapshot.next == ("clarify",)
assert len(snapshot.tasks) == 1
assert snapshot.tasks[0].name == "clarify"
assert snapshot.tasks[0].interrupts[0].value == {
    "kind": "business_clarification",
    "question": "请提供运单号",
}
```

Run: `Set-Location backend; uv run pytest tests/test_chat_graph_clarification.py::test_clarify_route_suspends_with_typed_payload -q`

Expected: FAIL because clarify node/edge does not yet suspend。

- [x] **Step 5.4: RED — 写 resume 后重新识别测试**

fake structured runnable 按顺序返回 CLARIFY、BUSINESS。首次调用后执行 `graph.ainvoke(Command(resume="YD2026001"), config, context=runtime_context)`；断言第二次 structured call 的历史末尾依次是 `AIMessage("请提供运单号")` 和 `HumanMessage("YD2026001")`，最终走到 BUSINESS boundary。

- [x] **Step 5.5: GREEN — 实现完整三路 builder 与最小 interrupt/resume 节点**

```python
def clarify_node(state: ChatState) -> dict[str, list[BaseMessage]]:
    result = state["business_understanding"]
    payload = ClarificationInterruptPayload(
        question=result.clarification_question or ""
    )
    resumed_content = interrupt(payload.model_dump(mode="json"))
    if not isinstance(resumed_content, str) or not resumed_content.strip():
        raise ValueError("clarification resume content must be non-blank text")
    return {
        "messages": [
            AIMessage(content=payload.question),
            HumanMessage(content=resumed_content.strip()),
        ]
    }
```

Builder 注册 `business_understanding`、现有 `llm`、`business_boundary`、`clarify`，添加 `START -> business_understanding`、条件边、两条 END 边和 `clarify -> business_understanding`；不得把 question 在首次 suspend 前写入 Graph messages，避免 resume 时重复。

- [x] **Step 5.6: Verify GREEN — 运行三路拓扑和恢复测试**

Run: `Set-Location backend; uv run pytest tests/test_chat_graph.py tests/test_chat_graph_routing.py tests/test_chat_graph_clarification.py -q`

Expected: 三条 route 全部 PASS；CLARIFY 首次挂起，resume 后同 thread 重评并完成。

```text
RED: Set-Location backend; uv run pytest tests/test_chat_graph_routing.py::test_non_business_graph_calls_structured_and_ordinary_model_once tests/test_chat_graph_routing.py::test_business_graph_ends_at_boundary_without_ordinary_model_call -q
Exit: 1
Observed: NON_BUSINESS structured 调用为 0；BUSINESS 错误调用 ordinary model。

RED: Set-Location backend; uv run pytest tests/test_chat_graph_clarification.py::test_clarify_route_suspends_with_typed_payload -q
Exit: 1
Observed: snapshot.next 为 ()，尚未在 clarify 挂起。

RED: Set-Location backend; uv run pytest tests/test_chat_graph_clarification.py::test_clarify_resume_adds_question_and_answer_before_reclassification tests/test_chat_graph_clarification.py::test_clarify_resume_rejects_non_text_or_blank_content -q
Exit: 1
Observed: resume 后无第二次 structured call，非法 resume 未抛 ValueError。

GREEN: Set-Location backend; uv run pytest tests/test_chat_graph.py tests/test_chat_graph_routing.py tests/test_chat_graph_clarification.py -q
Exit: 0
Observed: 17 passed in 1.44s（控制器独立复跑）；三路、首次挂起、同 thread resume/reclassify 和非法 resume 均通过。

REGRESSION: Set-Location backend; uv run pytest -q -m "not integration"
Exit: 0
Observed: 523 passed, 3 skipped, 2 deselected in 14.11s（控制器独立复跑）。
```

- [x] **Step 5.7: REFACTOR — 消除测试 fake 重复但不增加生产行为**

共享的顺序 structured fake 仅放在测试辅助模块或当前测试文件内；禁止为方便测试向生产模型增加 test-only 方法。再次运行 Step 5.6。

- [x] **Step 5.8: Commit**

```powershell
git add backend/app/domains/chat/graph backend/tests/test_chat_graph.py backend/tests/test_chat_graph_routing.py backend/tests/test_chat_graph_clarification.py
git commit -m "feat(chat): interrupt and resume clarification"
```

---

## Task 6: Public SSE Contract and Interrupt Projection

**Deliverable:** 后端公开协议接受 `finish_reason=interrupt`，并把受支持的 LangGraph interrupt 投影为领域 payload；未知或畸形 payload 明确失败。

**Files:**

- Modify: `backend/app/contracts/chat/stream.py`
- Modify: `backend/app/services/chat_api/streaming.py`
- Modify: `backend/tests/test_chat_contracts.py`
- Modify: `backend/tests/test_chat_sse_adapter.py`

**Interfaces:**

- Produces: `CompletionFinishReason = Literal["stop", "interrupt"]`。
- Produces: `project_clarification_interrupt(event: dict[str, object]) -> ClarificationInterruptPayload | None`。
- 非 interrupt event 返回 `None`；包含 `__interrupt__` 但 schema 不受支持时抛 `ValueError`，交由 Producer 现有 error path 处理。

- [x] **Step 6.1: RED — 写 completed 两种 finish reason 契约测试**

```python
def test_completed_payload_accepts_only_stop_or_interrupt():
    assert CompletedPayload(assistant_message_id=1).finish_reason == "stop"
    assert CompletedPayload(assistant_message_id=1,
                            finish_reason="interrupt").finish_reason == "interrupt"
    with pytest.raises(ValidationError):
        CompletedPayload(assistant_message_id=1, finish_reason="length")
```

Run: `Set-Location backend; uv run pytest tests/test_chat_contracts.py::test_completed_payload_accepts_only_stop_or_interrupt -q`

Expected: FAIL because current Literal only accepts `stop`。

- [x] **Step 6.2: GREEN — 最小扩展 CompletedPayload**

只把 `Literal["stop"]` 改成 `Literal["stop", "interrupt"]` 并保留默认 `stop`；不得新增终态 event 类型。

- [x] **Step 6.3: RED — 写真实 LangGraph v2 interrupt 事件形状的投影测试**

```python
event = {
    "event": "on_chain_stream",
    "data": {"chunk": {"__interrupt__": (
        Interrupt(value={"kind": "business_clarification",
                         "question": "请提供运单号"}, id="internal-id"),
    )}},
}
payload = project_clarification_interrupt(event)
assert payload.model_dump(mode="json") == {
    "kind": "business_clarification", "question": "请提供运单号"
}
assert "internal-id" not in payload.model_dump_json()
```

另写两个单行为测试：普通 `on_chat_model_stream` 返回 `None`；`__interrupt__` 中的 `kind`、question 或数量不合法时抛 `ValueError`。

- [x] **Step 6.4: Verify RED — 证明 adapter 尚不识别 interrupt**

Run: `Set-Location backend; uv run pytest tests/test_chat_sse_adapter.py -q`

Expected: FAIL with missing `project_clarification_interrupt`。

```text
RED: Set-Location backend; uv run pytest tests/test_chat_contracts.py::test_completed_payload_accepts_only_stop_or_interrupt -q
Exit: 1
Observed: finish_reason="interrupt" 被旧 Literal["stop"] 拒绝。

RED: Set-Location backend; uv run pytest tests/test_chat_sse_adapter.py -q
Exit: 1
Observed: 5 failed, 3 passed；缺少 project_clarification_interrupt，失败来自目标能力缺失。
```

- [x] **Step 6.5: GREEN — 实现严格 interrupt 投影**

只接受 `event="on_chain_stream"`、`data.chunk.__interrupt__` 为单元素序列、元素具有 `.value`，且 value 能通过 `ClarificationInterruptPayload.model_validate`；不序列化 `.id`、repr、metadata、run_id。

- [x] **Step 6.6: Verify GREEN — 运行 SSE 编码与契约回归**

Run: `Set-Location backend; uv run pytest tests/test_chat_contracts.py tests/test_chat_sse_adapter.py -q`

Expected: 原有 metadata/content_delta/completed/error 帧不变；新增 interrupt 投影 PASS。

```text
GREEN: Set-Location backend; uv run pytest tests/test_chat_contracts.py tests/test_chat_sse_adapter.py -q
Exit: 0
Observed: 25 passed in 0.41s（控制器独立复跑）；公开 CompletionFinishReason alias、字段复用、合法真实 Interrupt 投影与所有安全拒绝路径通过。

REGRESSION: Set-Location backend; uv run pytest -q -m "not integration"
Exit: 0
Observed: 530 passed, 3 skipped, 2 deselected。
```

- [x] **Step 6.7: Commit**

```powershell
git add backend/app/contracts/chat/stream.py backend/app/services/chat_api/streaming.py backend/tests/test_chat_contracts.py backend/tests/test_chat_sse_adapter.py
git commit -m "feat(chat): expose clarification finish reason"
```

---

## Task 7: Completion Producer Persists Intentional Clarification

**Deliverable:** Producer 收到受支持中断后，按 `metadata → content_delta(question) → ASSISTANT commit → completed(interrupt)` 顺序交付；畸形中断走唯一 error 终态。

**Files:**

- Modify: `backend/app/domains/chat/services/runtime.py`
- Modify: `backend/tests/test_chat_completion_producer.py`
- Modify: `backend/tests/test_chat_completion_disconnect.py`

**Interfaces:**

- Internal result: `GraphCompletion(content: str, finish_reason: CompletionFinishReason)`，普通回答为 `stop`，澄清问题为 `interrupt`。
- `_commit_assistant` 继续复用现有业务消息事务，不新增 clarification 专用表或字段。

- [x] **Step 7.1: RED — 写中断交付和持久化顺序测试**

扩展 FakeGraph，使其 yield Task 6 的 `on_chain_stream/__interrupt__` 事件；断言：

```python
assert [event for event, _ in publisher.events] == [
    "metadata", "content_delta", "completed"
]
assert publisher.events[1][1].content == "请提供运单号"
assert session.added[0].content == "请提供运单号"
assert calls.index("assistant_commit") < calls.index("publish_completed")
assert publisher.events[-1][1].finish_reason == "interrupt"
```

Run: `Set-Location backend; uv run pytest tests/test_chat_completion_producer.py::test_clarification_interrupt_persists_before_interrupted_completion -q`

Expected: FAIL，因为现有 producer 忽略 interrupt 并保存空回答/stop。

- [x] **Step 7.2: RED — 写畸形/未知中断安全失败测试**

FakeGraph yield `kind="unknown"` 或空 question；断言事件为 `metadata,error`，没有 ASSISTANT、没有 completed、错误 payload 不含 raw interrupt/id。

- [x] **Step 7.3: GREEN — 引入单一 GraphCompletion 收集结果**

在消费每个 graph event 时先投影文本 delta，再检查 clarification interrupt。普通文本按原顺序发布并累积；受支持 interrupt 将 question 转成一个 `ContentDeltaPayload` 发布并立即形成 `GraphCompletion(question, "interrupt")`；Graph 正常 END 则形成 `GraphCompletion(joined_text, "stop")`。

`run()` 使用返回的 finish reason 构造 `CompletedPayload`；ASSISTANT commit 仍在 completed 之前，任一异常仍只发布一个 error。

- [x] **Step 7.4: RED/GREEN — 写断连后中断仍持久化测试**

先让 subscriber 收到 metadata 后 detach，再释放 gated interrupt graph；RED 应显示当前 fake/producer 不支持中断，GREEN 后断言 producer task 完成、澄清问题已保存、registry active_count 回到 0、断连未取消 Graph。

- [x] **Step 7.5: Verify GREEN — 运行 Producer、断连与失败一致性测试**

Run: `Set-Location backend; uv run pytest tests/test_chat_completion_producer.py tests/test_chat_completion_disconnect.py -q`

Expected: 普通 stop、澄清 interrupt、Graph failure、commit failure、browser detach 全部 PASS，且没有重复终态。

```text
RED: Set-Location backend; uv run pytest tests/test_chat_completion_producer.py::test_clarification_interrupt_persists_before_interrupted_completion -q
Exit: 1
Observed: 旧 Producer 只发 metadata, completed，缺少 clarification delta。

RED: Set-Location backend; uv run pytest tests/test_chat_completion_producer.py -q -k unsupported_interrupt
Exit: 1
Observed: 未知 kind/空 question 被忽略并错误保存空 ASSISTANT，而非 metadata,error。

RED: Set-Location backend; uv run pytest tests/test_chat_completion_disconnect.py::test_disconnect_after_metadata_still_persists_clarification_interrupt -q
Exit: 1
Observed: detach 后后台任务存入空串而非澄清问题。

RED: Set-Location backend; uv run pytest tests/test_chat_completion_producer.py::test_clarification_interrupt_never_streams_classifier_output -q
Exit: 1
Observed: classifier JSON/reasoning 作为额外 content_delta 泄漏。

RED: Set-Location backend; uv run pytest tests/test_chat_completion_disconnect.py::test_detach_unblocks_publish_when_channel_queue_is_full -q
Exit: 1
Observed: 16 槽队列满后第 17 次 publish 阻塞，detach 未在 0.1s 内唤醒。

GREEN: Set-Location backend; uv run pytest tests/test_chat_completion_producer.py tests/test_chat_completion_disconnect.py tests/test_chat_completion_api.py -q
Exit: 0
Observed: 21 passed in 1.93s（控制器独立复跑）；顺序、泄漏隔离、唯一终态、断连与满队列背压均通过。

REGRESSION: Set-Location backend; uv run pytest -q -m "not integration"
Exit: 0
Observed: 537 passed, 3 skipped, 2 deselected in 14.70s（控制器独立复跑）。
```

- [x] **Step 7.6: Commit**

```powershell
git add backend/app/domains/chat/services/runtime.py backend/tests/test_chat_completion_producer.py backend/tests/test_chat_completion_disconnect.py
git commit -m "feat(chat): persist clarification interruptions"
```

---

## Task 8: Pending Checkpoint Detection and Same-Thread Resume

**Deliverable:** 已拥有会话的下一条非空消息在 USER 事务提交后自动恢复唯一受支持的 clarification checkpoint；普通会话仍从新 HumanMessage 开始。

**Files:**

- Modify: `backend/app/domains/chat/services/runtime.py`
- Modify: `backend/tests/test_chat_completion_producer.py`
- Modify: `backend/tests/test_chat_completion_api.py`
- Create: `backend/tests/test_chat_completion_resume.py`

**Interfaces:**

- Produces: `async resolve_graph_input(graph, config, content) -> dict[str, list[HumanMessage]] | Command`。
- 无 pending task 返回 `{"messages": [HumanMessage(content=content)]}`。
- 唯一 pending task 必须是 `task.name == "clarify"` 且含一个合法 Business clarification interrupt，随后返回 `Command(resume=content)`。
- 未知 task、多任务、多 interrupt 或畸形 payload 抛 `ValueError`，不得误启新轮次。

- [x] **Step 8.1: RED — 写无 checkpoint 的普通输入测试**

FakeGraph 的 `aget_state(config)` 返回 `values={}`, `next=()`, `tasks=()`；执行 producer 后断言 `astream_events` 输入仍是现有 HumanMessage dict，thread ID 仍为 conversation ID 字符串。

- [x] **Step 8.2: RED — 写合法 pending clarification 的 Command 测试**

Fake snapshot 形状必须与 LangGraph 当前 API 对齐：`next=("clarify",)`，一个 task，task.name 为 clarify，task.interrupts 含 Task 6 的合法 Interrupt。断言传给 `astream_events` 的首个参数满足：

```python
assert isinstance(graph_input, Command)
assert graph_input.resume == "YD2026001"
assert config == {"configurable": {"thread_id": "1001"}}
```

Run: `Set-Location backend; uv run pytest tests/test_chat_completion_resume.py -q`

Expected: FAIL，因为 producer 尚未调用 `aget_state`，总是创建新 HumanMessage 输入。

- [x] **Step 8.3: RED — 写未知 pending 状态不降级为普通轮次测试**

分别提供未知 task name、两个 pending tasks、空 question 三个 snapshot；断言 producer 发布 metadata 后进入 error，`astream_events` 未调用，原 checkpoint 未被 resume 或覆盖。

- [x] **Step 8.4: GREEN — 实现严格 snapshot 检测和 Command(resume)**

在 `_consume_graph_events` 启动流之前，使用相同 config 调用 `graph.aget_state(config)`。只把 Task 5 创建的 interrupt 识别为 resume；不要接受客户端提供的 runtime identifiers，也不要读取业务消息表来猜 pending 状态。

```python
async def resolve_graph_input(graph, config, content):
    snapshot = await graph.aget_state(config)
    if not snapshot.tasks:
        return {"messages": [HumanMessage(content=content)]}
    if snapshot.next != (CLARIFY_NODE,) or len(snapshot.tasks) != 1:
        raise ValueError("unsupported pending graph state")
    task = snapshot.tasks[0]
    if task.name != CLARIFY_NODE or len(task.interrupts) != 1:
        raise ValueError("unsupported pending graph task")
    ClarificationInterruptPayload.model_validate(task.interrupts[0].value)
    return Command(resume=content)
```

- [x] **Step 8.5: RED — 写 API 所有权与提交顺序测试**

扩展 `test_chat_completion_api.py`：

- foreign conversation 返回 404，且 fake graph 的 `aget_state/astream_events` 调用数都为 0；
- USER session commit 失败时 Registry/Producer 未启动，pending checkpoint 保持未消费；
- 合法 owned turn 的首个 SSE 仍是持久化后的 metadata；
- request 包含 `checkpoint_id`, `interrupt_id`, `command`, `route`, `intent` 任一字段均返回 422 且无写入。

- [x] **Step 8.6: Verify GREEN — 运行恢复与 API 回归**

Run: `Set-Location backend; uv run pytest tests/test_chat_completion_resume.py tests/test_chat_completion_producer.py tests/test_chat_completion_api.py tests/test_chat_conversation_service.py -q`

Expected: 普通输入与 resume 输入分流正确，所有权隐藏和 commit-before-execute 保持不变。

```text
RED: Set-Location backend; uv run pytest tests/test_chat_completion_resume.py -q
Exit: 1
Observed: 8 failed；未调用 aget_state，合法 pending 仍传 HumanMessage，非法 pending 误启新轮次。

RED: Set-Location backend; uv run pytest tests/test_chat_completion_resume.py -q -k "next_without_tasks"
Exit: 1
Observed: 2 failed；clarify/unknown next + empty tasks 被错误降级为普通轮次。

GREEN: Set-Location backend; uv run pytest tests/test_chat_completion_resume.py -q
Exit: 0
Observed: 10 passed；仅 next/tasks 同为空时创建普通输入，唯一合法 clarify pending 返回 Command(resume)。

REGRESSION: Set-Location backend; uv run pytest tests/test_chat_completion_resume.py tests/test_chat_completion_producer.py tests/test_chat_completion_api.py tests/test_chat_conversation_service.py tests/test_chat_completion_disconnect.py -q
Exit: 0
Observed: 44 passed in 2.11s（控制器独立复跑）；所有权、commit-before-state、metadata-first、422 extra fields 与断连回归通过。

REGRESSION: Set-Location backend; uv run pytest -q -m "not integration"
Exit: 0
Observed: 553 passed, 3 skipped, 2 deselected in 11.62s（控制器独立复跑）。
```

- [x] **Step 8.7: Commit**

```powershell
git add backend/app/domains/chat/services/runtime.py backend/tests/test_chat_completion_resume.py backend/tests/test_chat_completion_producer.py backend/tests/test_chat_completion_api.py
git commit -m "feat(chat): resume pending clarification turns"
```

---

## Task 9: Frontend Finish-Reason Handling

**Deliverable:** TypeScript client 把 `stop` 和 `interrupt` 都视为成功终态；完成后 composer 恢复可输入，用户下一条消息继续使用同一 conversation ID。

**Files:**

- Modify: `frontend/src/app/chat/types.ts`
- Modify: `frontend/src/app/chat/api.ts`
- Modify: `frontend/src/app/chat/api.test.ts`
- Modify only if behavior requires: `frontend/src/app/chat/page.tsx`

**Interfaces:**

- Produces: `type CompletionFinishReason = "stop" | "interrupt"`。
- `streamCompletion(options) -> Promise<CompletionFinishReason>`；收到 completed 前流结束视为协议错误。
- `interrupt` 不抛异常，不要求 checkpoint ID，并允许页面现有 finally 把 `sending` 恢复为 false。

- [x] **Step 9.1: RED — 写 stop/interrupt 成功终态测试**

使用 `ReadableStream` 分别返回：

```text
event: completed
data: {"assistant_message_id":"3001","finish_reason":"stop"}

event: completed
data: {"assistant_message_id":"3002","finish_reason":"interrupt"}
```

断言 `streamCompletion` 分别 resolve `stop` 和 `interrupt`；未知 finish reason、只有 delta 后 EOF、error event 分别 reject。

Run: `Set-Location frontend; node --experimental-strip-types --test src/app/chat/api.test.ts`

Expected: FAIL，因为现有函数不解析 completed 且返回 `undefined`。

```text
RED: Set-Location frontend; node --experimental-strip-types --test src/app/chat/api.test.ts
Exit: 1
Observed: stop/interrupt 实际返回 undefined；未知 reason 与无 completed EOF 未 reject。
```

- [x] **Step 9.2: GREEN — 增加窄类型和 completed 解析**

```typescript
export type CompletionFinishReason = "stop" | "interrupt";

function isFinishReason(value: unknown): value is CompletionFinishReason {
  return value === "stop" || value === "interrupt";
}
```

`streamCompletion` 保存并返回唯一 completed reason；收到 completed 后取消/结束 reader 消费，不把 interrupt 当 error。不得向 request body 添加 resume 字段。

- [x] **Step 9.3: Verify GREEN — 运行前端单测、lint、build**

Run: `Set-Location frontend; npm test; npm run lint; npm run build`

Expected: 三个命令全部 exit 0；现有 metadata/content_delta/error 行为不变。

```text
RED: node --experimental-strip-types --test src/app/chat/api.test.ts
Exit: 1
Observed: 合法 completed 后 underlying cancel rejection 覆盖 interrupt 成功结果。

GREEN: Set-Location frontend; npm test; npm run lint; npm run build
Exit: 0 / 0 / 0
Observed: 11/11 tests passed；lint 与 Next.js production build 通过（控制器独立复跑）。既有 ExperimentalWarning 与 MODULE_TYPELESS_PACKAGE_JSON warning 保留为基线噪声。
```

- [x] **Step 9.4: Commit**

```powershell
git add frontend/src/app/chat/types.ts frontend/src/app/chat/api.ts frontend/src/app/chat/api.test.ts frontend/src/app/chat/page.tsx
git commit -m "feat(chat-ui): handle clarification completion"
```

---

## Task 10: PostgreSQL End-to-End, Evaluation Report, and Documentation

**Deliverable:** 使用真实 PostgreSQL checkpointer 与业务表证明三条 route、澄清持久化/恢复、同 thread 重评和终态顺序；最后更新文档为真实测试结果，不编造在线模型准确率。

**Files:**

- Create: `backend/tests/test_business_understanding_postgres.py`
- Modify: `backend/tests/chat_postgres_support.py`
- Modify: `docs/my-specs/ke-engine架构讨论过程与阶段性结论.md`
- Modify: `docs/my-specs/项目中意图识别提示词的优化.md`
- Modify: `openspec/changes/add-business-understanding/tasks.md`（只勾选已取得证据的步骤并追加实际命令输出摘要）

**Interfaces:**

- Integration fake model 必须同时支持 `with_structured_output` 与普通 `ainvoke`，按测试预设顺序返回结构化决策或 AIMessage；不访问在线模型。
- 业务 conversation ID 继续等于 LangGraph `thread_id`。
- 评测报告分列 route、intent、key entity、clarification、schema validity，不合并为一个掩盖问题的总分。

- [x] **Step 10.1: RED — 写完整 CLARIFY → resume → BUSINESS 集成测试**

测试必须执行两次 `CompletionProducer.run`：第一次输入“查一下我的运单”，断言 ASSISTANT 澄清已落业务表、completed reason 为 interrupt、snapshot.next 为 clarify；第二次先把 “YD2026001” 作为 USER 业务消息提交，再运行 producer，断言 graph 收到 `Command(resume="YD2026001")`、structured model 看到澄清问答历史、最终 BUSINESS boundary 落库、completed reason 为 stop、snapshot 不再 pending。

Run: `Set-Location backend; uv run pytest tests/test_business_understanding_postgres.py::test_clarification_persists_resumes_and_reclassifies_on_same_thread -q -m integration`

Expected: 在实现完成前 FAIL；若 PostgreSQL 不可用应明确报告基础设施错误，不把 skip 记作 RED 或 GREEN。

```text
RED: Set-Location backend; uv run pytest tests/test_business_understanding_postgres.py::test_clarification_persists_resumes_and_reclassifies_on_same_thread -q -m integration
Exit: 1
Observed: 首次 CLARIFY、持久化、pending、Command(resume) 与历史重评已走通；第二次 BUSINESS 缺少 boundary content_delta，旧 Producer 保存空回答。

GREEN: 同一命令
Exit: 0
Observed: 1 passed；第二次 boundary delta、ASSISTANT commit、completed(stop) 与 snapshot clear 均通过。
```

- [x] **Step 10.2: RED/GREEN — 增加 NON_BUSINESS 与 BUSINESS 集成场景**

NON_BUSINESS 断言 general model answer 被流式发布并落库；BUSINESS 断言只落 `BUSINESS_BOUNDARY_MESSAGE`，普通 model 调用次数为 0。分别先写测试并看到预期 RED，再使用已实现代码使其 GREEN，不为集成测试增加专用生产分支。

- [x] **Step 10.3: Verify GREEN — 运行所有 Chat 单元与集成回归**

```powershell
Set-Location backend
uv run pytest tests/test_business_understanding_models.py tests/test_business_understanding_prompt.py tests/test_business_understanding_evaluation.py tests/test_business_understanding_node.py tests/test_chat_graph.py tests/test_chat_graph_routing.py tests/test_chat_graph_clarification.py tests/test_chat_contracts.py tests/test_chat_sse_adapter.py tests/test_chat_completion_producer.py tests/test_chat_completion_resume.py tests/test_chat_completion_api.py tests/test_chat_completion_disconnect.py tests/test_chat_conversation_service.py -q
uv run pytest tests/test_chat_langgraph_postgres.py tests/test_chat_failure_consistency_postgres.py tests/test_business_understanding_postgres.py -q -m integration
```

Expected: 两个命令 exit 0，无 warning/error；失败时只修复本变更引入的回归，并为每个 bug 先补最小复现测试。

```text
GREEN: brief 指定的 14 个 Chat 单元文件
Exit: 0
Observed: 113 passed in 2.54s（控制器独立复跑）。

INTEGRATION: uv run pytest tests/test_chat_langgraph_postgres.py tests/test_chat_failure_consistency_postgres.py tests/test_business_understanding_postgres.py -q -m integration
Exit: 0
Observed: 5 passed in 2.89s（真实 PostgreSQL checkpointer、业务表与隔离 schema）。
```

- [x] **Step 10.4: Verify GREEN — 运行全仓后端与前端回归**

```powershell
Set-Location backend
uv run pytest -q -m "not integration"
Set-Location ../frontend
npm test
npm run lint
npm run build
```

Expected: 所有命令 exit 0；记录实际测试数量和耗时，不使用“应该通过”。

```text
REGRESSION: Set-Location backend; uv run pytest -q -m "not integration"
Exit: 0
Observed: 563 passed, 3 skipped, 5 deselected in 6.34s（控制器独立复跑）。

FRONTEND: Set-Location frontend; npm test; npm run lint; npm run build
Exit: 0 / 0 / 0
Observed: 11/11 tests passed；lint 无 error；Next.js production build 成功。保留既有 Node ExperimentalWarning/MODULE_TYPELESS_PACKAGE_JSON warning。
```

- [x] **Step 10.5: 运行离线确定性评测并记录分维度结果**

Run: `Set-Location backend; uv run pytest tests/test_business_understanding_evaluation.py -q -s`

将实际输出写入提示词优化文档；离线 fake/dataset 结果标注为“契约与评测器验证”，不得描述成真实大模型准确率。若随后人工运行 live model，必须单独记录模型名、Prompt 版本、样本版本、日期、各维度指标和失败样例。

```text
EVALUATION: Set-Location backend; uv run pytest tests/test_business_understanding_evaluation.py -q -s
Exit: 0
Observed: 3 passed；cases=18, live_model=false；route=18/18, intent=18/18, key_entities=24/24, clarification=18/18, schema_validity=18/18。结果仅为 deterministic oracle contract/evaluator validation。
```

- [x] **Step 10.6: 更新实现文档且保持延期范围明确**

文档只写已经由测试证明的拓扑、finish reason、持久化顺序和验证命令；继续明确 RAG、SQL、引用、证据校验、细粒度意图不在本 change 内。

- [x] **Step 10.7: OpenSpec 与格式验证**

```powershell
openspec validate add-business-understanding --type change --strict
git diff --check
git status --short
```

Expected: OpenSpec valid、`git diff --check` exit 0、status 只包含本 change 预期文件。

```text
OPENSPEC: openspec validate add-business-understanding --type change --strict
Exit: 0
Observed: Change 'add-business-understanding' is valid。

FORMAT: git diff --check 986cdb9..91ba7ff
Exit: 0
Observed: 无 whitespace error。
```

- [x] **Step 10.8: Commit**

```powershell
git add backend/tests/test_business_understanding_postgres.py backend/tests/chat_postgres_support.py docs/my-specs openspec/changes/add-business-understanding/tasks.md
git commit -m "test(chat): verify business understanding flow"
```

---

## Final TDD Compliance Gate

以下项目全部有证据后，才可把 change 标记为 implemented：

- [x] 每个新增生产函数至少有一个先失败后通过的行为测试。
- [x] 每个 RED 都因目标能力缺失而失败，不是语法、fixture、依赖或环境错误。
- [x] 每个 GREEN 都运行了当前测试和列出的回归测试。
- [x] BUSINESS、NON_BUSINESS、CLARIFY 三条路径均通过真实 StateGraph 测试。
- [x] CLARIFY 通过真实 checkpointer 证明首次挂起、同 thread resume 和重新识别。
- [x] 普通回答与澄清问题均证明 ASSISTANT commit 发生在 completed 之前。
- [x] 畸形 structured output 和畸形 interrupt 都走唯一 error 终态且不落部分 ASSISTANT。
- [x] 客户端断连不取消已接受的普通回答或澄清持久化。
- [x] 公开请求没有 resume 内部字段，公开 SSE 没有 reasoning、分类 JSON 或 Interrupt ID。
- [x] 前端把 `stop`、`interrupt` 作为成功终态并拒绝未知值。
- [x] 后端非 integration、PostgreSQL integration、前端 test/lint/build 全部有新鲜的 exit 0 输出。
- [x] OpenSpec strict validation 和 `git diff --check` 均通过。
- [x] 文档中的测评数字来自实际输出，并明确区分 deterministic 与 live-model 结果。
