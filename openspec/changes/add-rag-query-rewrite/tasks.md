# RAG Query Rewrite Graph TDD Implementation Plan

**Goal:** 在不实现 Router、Retriever、EvidencePackage、MCP API 或独立 Query Rewrite service 的前提下，为 RAG domain 增加可独立测试和运行的一对一 Query Rewrite LangGraph 阶段。

**Architecture:** Query Rewrite 是完整 RAG Graph 的第一个阶段。阶段专属契约、Prompt 与评测辅助代码位于 `graph/query_rewrite/`，执行逻辑位于 `graph/nodes/query_rewrite.py`。调用方提供纯请求数据，model 通过 runtime 注入；失败时单次降级为原始问题。未来完整 RAG 管线形成后，再在 `domains/rag/services/` 提供管线级 service。

**Test style:** 参考 Chat `business_understanding` 的测试方式，直接测试阶段模型、Prompt、可调用 node 函数、runtime wrapper 和最小 Graph；只参考其组织方式，不强制逐项对齐。

## Global Constraints

- 严格执行 `RED → Verify RED → GREEN → Verify GREEN → REFACTOR → Verify GREEN`。
- 每次 Query Rewrite 最多调用模型一次；普通失败或无效输出直接令 `standalone_query = original_query`。
- 不新增 `query_rewrite/service.py`，也不暴露 Query Rewrite 单节点 service。
- 不实现多查询、问题拆解、Router、Retriever、SQL、Cypher、Rerank、EvidencePackage、MCP API、重试或 checkpoint。
- Query Rewrite 不接收 `conversation_id`，不访问 Chat persistence、Redis、数据库、checkpoint 或调用方记忆。
- state 只包含可序列化请求数据、结果、状态、有限失败码和非敏感 warning。
- domain 模块导入不得创建模型客户端、读取 settings 或初始化 Langfuse。
- `RunnableConfig` 必须原样传给结构化模型调用；Langfuse 只由调用方以 callback 注入。
- 默认 pytest 完全离线；真实模型评测只能通过显式命令运行。
- 语义质量不得用关键词包含、正则、token overlap、编辑距离或参考答案 exact match 代替；只能由人工或经校准的 LLM Judge 评估。
- 每个 Verify 步骤记录命令、退出码和关键结果。

## Planned File Map

| Path | Responsibility |
|---|---|
| `backend/app/domains/rag/graph/query_rewrite/models.py` | 阶段输入、输出、状态枚举、失败码和 update 契约 |
| `backend/app/domains/rag/graph/query_rewrite/prompt.py` | 版本化 Prompt 与输入消息构造 |
| `backend/app/domains/rag/graph/query_rewrite/evaluation.py` | 本地评测 case 与客观输出契约 scorer |
| `backend/app/domains/rag/graph/state.py` | 可序列化的最小 Graph state |
| `backend/app/domains/rag/graph/context.py` | 不进入 state 的 model runtime dependency |
| `backend/app/domains/rag/graph/nodes/query_rewrite.py` | 单次模型调用、fallback、state/runtime 适配 |
| `backend/app/domains/rag/graph/builder.py` | `START -> query_rewrite -> END` 拓扑 |
| `backend/app/entrypoints/rag_query_rewrite_studio.py` | 独立 LangGraph Studio 装配入口 |
| `backend/app/evaluation/rag_query_rewrite.py` | 显式真实模型评测命令 |
| `backend/tests/rag_query_rewrite_test_support.py` | 仅替代模型边界的完整 test doubles |
| `backend/tests/fixtures/query_rewrite_cases.json` | 约束保留和上下文改写样例 |
| `backend/tests/test_rag_query_rewrite_*.py` | 契约、Prompt、node、Graph、Studio 和评测测试 |

## Evidence Template

```text
RED: <exact command>
Exit: <non-zero exit code>
Observed: <expected missing behavior>

GREEN: <exact command>
Exit: 0
Observed: <passed test count>

REGRESSION: <exact command>
Exit: 0
Observed: <passed test count>
```

---

## Task 1: Query Rewrite Contracts and Serializable State

**Deliverable:** 拒绝空白值、额外字段和重复当前问题，并能 JSON 序列化的阶段契约与 Graph state。

- [x] 1.1 RED：新增 `test_rag_query_rewrite_models.py`，覆盖有序上下文、业务上下文、空白字段、额外字段、当前问题重复和 JSON 序列化。
- [x] 1.2 Verify RED：`uv run pytest tests/test_rag_query_rewrite_models.py -q`，Exit 1，9 个失败均为阶段契约或 state 尚不存在。
- [x] 1.3 GREEN：实现 `graph/query_rewrite/models.py`、包导出及 `graph/state.py`。
- [x] 1.4 Verify GREEN：`uv run pytest tests/test_rag_query_rewrite_models.py -q`，Exit 0，9 passed。
- [x] 1.5 REFACTOR：依赖扫描无命中；本地未安装 Ruff，最终验证时再次检查工具可用性。
- [x] 1.6 Commit：`feat(rag): add query rewrite graph contracts`。

## Task 2: Versioned Constrained Retrieval Prompt

**Deliverable:** 结构稳定、版本化且只要求一个结构化查询的 Prompt。

- [x] 2.1 RED：新增 `test_rag_query_rewrite_prompt.py`，覆盖消息分区、JSON 输入、当前问题优先、硬约束保留和禁止越界产物。
- [x] 2.2 Verify RED：`uv run pytest tests/test_rag_query_rewrite_prompt.py -q`，Exit 1，3 个失败均为 Prompt 模块尚不存在。
- [x] 2.3 GREEN：实现 `graph/query_rewrite/prompt.py`。
- [x] 2.4 Verify GREEN：Prompt 与模型契约测试 Exit 0，12 passed。
- [x] 2.5 REFACTOR：越界产物标识扫描无命中，编译检查通过。
- [x] 2.6 Commit：`feat(rag): add versioned query rewrite prompt`。

## Task 3: Single-call Query Rewrite Node Invocation

**Deliverable:** `invoke_query_rewrite(...)` 直接完成输入校验、一次结构化模型调用、config 透传和显式 fallback。

- [x] 3.1 RED：新增 test support 与 `test_rag_query_rewrite_node.py`，覆盖成功、schema 绑定、config 透传、模型失败、无效输出、无重试、取消传播和输入错误时不调用模型。
- [x] 3.2 Verify RED：`uv run pytest tests/test_rag_query_rewrite_node.py -q`，Exit 1，6 个失败均为 node invocation 尚不存在。
- [x] 3.3 GREEN：在 `graph/nodes/query_rewrite.py` 实现 `invoke_query_rewrite(...)`；fallback warning 常量位于阶段契约。
- [x] 3.4 Verify GREEN：node、Prompt 与模型测试 Exit 0，18 passed。
- [x] 3.5 REFACTOR：重试、并发双查询、异常字符串和多查询标识扫描无命中，编译检查通过。
- [x] 3.6 Commit：`feat(rag): add single-call query rewrite node`。

## Task 4: Runtime-injected Node Wrapper

**Deliverable:** 从 runtime context 取得 model、保留已有 warnings，并且导入纯净的 LangGraph node wrapper。

- [ ] 4.1 RED：在 node 测试中增加 runtime 注入、state 映射、warning 合并和 import purity 用例。
- [ ] 4.2 Verify RED：确认因 runtime context/wrapper 尚不存在而失败。
- [ ] 4.3 GREEN：实现 `graph/context.py`、`query_rewrite_node(...)` 与 `graph/nodes/__init__.py`。
- [ ] 4.4 Verify GREEN：运行全部 node 测试。
- [ ] 4.5 REFACTOR：确认 runtime 依赖不进入 state，模块导入不读取 settings 或创建 model。
- [ ] 4.6 Commit：`feat(rag): add runtime-injected query rewrite node`。

## Task 5: Independently Runnable Minimal LangGraph

**Deliverable:** 无 checkpointer 的 `START -> query_rewrite -> END` 最小 Graph。

- [ ] 5.1 RED：新增 `test_rag_query_rewrite_graph.py`，覆盖拓扑、成功输出、fallback 输出、config 透传、连续调用隔离和 JSON 序列化。
- [ ] 5.2 Verify RED：确认因 Graph builder 尚不存在而失败。
- [ ] 5.3 GREEN：实现 `graph/builder.py` 与 `graph/__init__.py`，支持 runtime model 和显式绑定 model。
- [ ] 5.4 Verify GREEN：运行 Graph、node、Prompt 与模型测试。
- [ ] 5.5 REFACTOR：确认只有一个业务节点且未配置 checkpointer。
- [ ] 5.6 Commit：`feat(rag): add minimal query rewrite graph`。

## Task 6: LangGraph Studio Development Entry

**Deliverable:** 复用生产 Graph/node 的开发期 Studio 入口。

- [ ] 6.1 RED：新增 `test_rag_query_rewrite_studio.py`，覆盖模型装配、可选 Langfuse callback、无 Langfuse 仍可运行及 `langgraph.json` 注册。
- [ ] 6.2 Verify RED：确认入口或注册尚不存在。
- [ ] 6.3 GREEN：实现 `app/entrypoints/rag_query_rewrite_studio.py` 并更新 `backend/langgraph.json`。
- [ ] 6.4 Verify GREEN：运行 Studio 与全部 Graph 测试。
- [ ] 6.5 REFACTOR：确认入口不读取 Chat 历史、不启用 checkpoint、不实现业务逻辑。
- [ ] 6.6 Commit：`feat(rag): add query rewrite studio graph`。

## Task 7: Objective Evaluation Contracts and Curated Cases

**Deliverable:** 只评分客观输出契约的 evaluator，以及覆盖高风险语义错误的固定样例。

- [ ] 7.1 RED：新增 `test_rag_query_rewrite_evaluation.py`，验证 28 条样例结构、分类覆盖、人工参考字段、case-specific rubric 与客观 scorer。
- [ ] 7.2 Verify RED：确认 evaluation 模块尚不存在。
- [ ] 7.3 GREEN：实现 `graph/query_rewrite/evaluation.py` 并复用现有 fixture。
- [ ] 7.4 Verify GREEN：运行 evaluation 测试与 Graph 回归集。
- [ ] 7.5 REFACTOR：确认 scorer 不访问人工参考字段，不使用关键词命中、正则、exact match、BLEU、ROUGE 或编辑距离评价语义。
- [ ] 7.6 Commit：`test(rag): add query rewrite evaluation cases`。

## Task 8: Explicit Live-model Evaluation

**Deliverable:** 默认跳过、显式开启才调用真实模型，并逐条走生产 node/Graph 的评测入口。

- [ ] 8.1 RED：新增 `test_rag_query_rewrite_live_evaluation.py`，覆盖默认 skip 和显式启用约束。
- [ ] 8.2 Verify RED：确认显式评测入口尚不存在。
- [ ] 8.3 GREEN：实现 `app/evaluation/rag_query_rewrite.py`，加载 settings/model/callback，逐条调用生产 Graph 并输出 JSONL。
- [ ] 8.4 Verify GREEN：运行默认离线测试，确认无网络调用。
- [ ] 8.5 REFACTOR：确认不复制 Rewrite 逻辑，不自动执行 Judge，不把未校准分数设为门禁。
- [ ] 8.6 Commit：`feat(rag): add explicit query rewrite evaluation`。

## Task 9: Full Verification and Documentation

**Deliverable:** OpenSpec、测试、静态检查与开发文档一致。

- [ ] 9.1 运行全部 Query Rewrite 测试。
- [ ] 9.2 运行受影响的 Chat/Graph 回归测试。
- [ ] 9.3 运行 Ruff、Pyright（如仓库配置）和 OpenSpec strict validation。
- [ ] 9.4 检查 diff：无 `service.py`、无 MCP/Router/Retriever 越界、无敏感异常入 state。
- [ ] 9.5 更新 `docs/my-specs/RAG查询链路与MCP服务.md` 中确有必要同步的实现状态，不改写已确认的架构原则。
- [ ] 9.6 Commit：`docs(rag): document query rewrite graph slice`。
