# RAG Graph Query Rewrite Stage TDD Implementation Plan

**Goal:** 在不实现 Router、Retriever、EvidencePackage、MCP API 或独立 Query Rewrite service 的前提下，为 RAG domain 增加可独立测试和运行的一对一 Query Rewrite LangGraph 阶段。

**Architecture:** Query Rewrite 是完整 RAG Graph 的第一个阶段。阶段专属契约、Prompt 与评测辅助代码位于 `graph/query_rewrite/`，执行逻辑位于 `graph/nodes/query_rewrite.py`。顶层始终使用管线级 `RagState`、`build_rag_graph(model=...)` 和 `rag` Studio 入口；模型在 Graph 装配期绑定，请求期只透传 config，不引入无实际需求的 runtime context。当前一节点拓扑只是完整管线的首个增量，不是 Query Rewrite 子图。未来完整 RAG 管线形成后，再在 `domains/rag/services/` 提供管线级 service。

**Test style:** 参考 Chat `business_understanding` 的测试方式，直接测试阶段模型、Prompt、可调用 node 函数和 RAG Graph 当前拓扑；只参考其测试组织方式，不复制 Chat 为动态切模设计的 runtime wrapper。

## Global Constraints

- 严格执行 `RED → Verify RED → GREEN → Verify GREEN → REFACTOR → Verify GREEN`。
- 每次 Query Rewrite 最多调用模型一次；普通失败或无效输出直接令 `standalone_query = original_query`。
- 不新增 `query_rewrite/service.py`，也不暴露 Query Rewrite 单节点 service。
- 不实现多查询、问题拆解、Router、Retriever、SQL、Cypher、Rerank、EvidencePackage、MCP API、重试或 checkpoint。
- Query Rewrite 不接收 `conversation_id`，不访问 Chat persistence、Redis、数据库、checkpoint 或调用方记忆。
- state 只包含可序列化请求数据和当前实际使用的 `standalone_query`。
- domain 模块导入不得创建模型客户端、读取 settings 或初始化 Langfuse。
- `RunnableConfig` 必须原样传给结构化模型调用；Langfuse 只由调用方以 callback 注入。
- 默认 pytest 完全离线；真实模型评测只能通过显式命令运行。
- 语义质量不得用关键词包含、正则、token overlap、编辑距离或参考答案 exact match 代替；只能由人工或经校准的 LLM Judge 评估。
- 每个 Verify 步骤记录命令、退出码和关键结果。

## Planned File Map

| Path | Responsibility |
|---|---|
| `backend/app/domains/rag/graph/query_rewrite/models.py` | 阶段输入、结构化模型输出和单字段 update 契约 |
| `backend/app/domains/rag/graph/query_rewrite/prompt.py` | 版本化 Prompt 与输入消息构造 |
| `backend/app/domains/rag/graph/query_rewrite/evaluation.py` | 本地评测 case 与客观输出契约 scorer |
| `backend/app/domains/rag/graph/state.py` | 随管线阶段增量扩展的 `RagState` |
| `backend/app/domains/rag/graph/nodes/query_rewrite.py` | 单次模型调用、fallback 和 state 适配 |
| `backend/app/domains/rag/graph/builder.py` | 完整 RAG Graph builder；当前拓扑为 `START -> query_rewrite -> END` |
| `backend/app/entrypoints/rag_studio.py` | 管线级 RAG LangGraph Studio 装配入口 |
| `backend/app/evaluation/rag_query_rewrite.py` | 显式真实模型评测命令 |
| `backend/tests/rag_query_rewrite_test_support.py` | 仅替代模型边界的完整 test doubles |
| `backend/tests/fixtures/query_rewrite_cases.json` | 约束保留和上下文改写样例 |
| `backend/tests/test_rag_query_rewrite_*.py` | Query Rewrite 阶段契约、Prompt、node 和评测测试 |
| `backend/tests/test_rag_graph.py`、`test_rag_studio.py` | 顶层 RAG Graph 与 Studio 测试 |

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

**Deliverable:** `query_rewrite_node(...)` 直接完成输入校验、一次结构化模型调用、config 透传和显式 fallback。

- [x] 3.1 RED：新增 test support 与 `test_rag_query_rewrite_node.py`，覆盖成功、schema 绑定、config 透传、模型失败、无效输出、无重试、取消传播和输入错误时不调用模型。
- [x] 3.2 Verify RED：`uv run pytest tests/test_rag_query_rewrite_node.py -q`，Exit 1，6 个失败均为 node invocation 尚不存在。
- [x] 3.3 GREEN：在 `graph/nodes/query_rewrite.py` 实现 `query_rewrite_node(...)`，失败时只返回原始查询。
- [x] 3.4 Verify GREEN：node、Prompt 与模型测试 Exit 0，18 passed。
- [x] 3.5 REFACTOR：重试、并发双查询、异常字符串和多查询标识扫描无命中，编译检查通过。
- [x] 3.6 Commit：`feat(rag): add single-call query rewrite node`。

## Task 4: Assembly-time Model Binding

**Deliverable:** Graph builder 在装配期把 model 绑定到 node；模块导入保持纯净，不定义仅用于模型注入的 runtime context。

- [x] 4.1 RED：测试要求 `query_rewrite_node(model=...)`、`build_rag_graph(model=...)`，并断言不存在 `RagRuntimeContext`。
- [x] 4.2 Verify RED：node、Graph、Studio 测试 Exit 1，13 个失败锁定旧 runtime wrapper、双模式 builder 和 context 文件。
- [x] 4.3 GREEN：node 接收装配期绑定的 model，builder 只保留一种装配模式，并删除 `graph/context.py`。
- [x] 4.4 Verify GREEN：node、RAG Graph、Studio、Prompt 与模型测试 Exit 0，33 passed。
- [x] 4.5 REFACTOR：保留 `RunnableConfig` callback/metadata 透传，确认无 runtime context 或旧调用入口残留。
- [x] 4.6 Commit：`refactor(rag): bind model during graph assembly`。

## Task 5: RAG Graph Initial Topology

**Deliverable:** 管线级 `RagState` 和 `build_rag_graph`，当前拓扑为无 checkpointer 的 `START -> query_rewrite -> END`。

- [x] 5.1 RED：新增 `test_rag_graph.py`，覆盖拓扑、成功输出、fallback 输出、config 透传、连续调用隔离和 JSON 序列化。
- [x] 5.2 Verify RED：Graph 测试 Exit 1，4 个失败均为 builder/公开导出尚不存在。
- [x] 5.3 GREEN：实现管线级 `RagState`、`build_rag_graph(model=...)` 与公开导出。
- [x] 5.4 Verify GREEN：Graph、node、Prompt 与模型测试 Exit 0，25 passed。
- [x] 5.5 REFACTOR：隐藏分支、retry/checkpointer/内部 compile 扫描无命中，编译与 diff 检查通过。
- [x] 5.6 Commit：`feat(rag): add minimal query rewrite graph`。

## Task 6: RAG LangGraph Studio Development Entry

**Deliverable:** 复用生产 RAG Graph/node 的管线级开发期 Studio 入口。

- [x] 6.1 RED：新增 `test_rag_studio.py`，覆盖模型装配、可选 Langfuse callback、无 Langfuse 仍可运行及 `langgraph.json` 注册。
- [x] 6.2 Verify RED：Studio 测试 Exit 1，3 个失败分别证明入口与注册尚不存在。
- [x] 6.3 GREEN：实现 `app/entrypoints/rag_studio.py`，以 `rag` 注册并更新 `backend/langgraph.json`。
- [x] 6.4 Verify GREEN：Studio 与全部 RAG Graph/Query Rewrite 阶段测试 Exit 0，32 passed。
- [x] 6.5 REFACTOR：Chat API、数据库、Redis、checkpoint 和 RAG service 引用扫描无命中，编译检查通过。
- [x] 6.6 Commit：`feat(rag): add query rewrite studio graph`。

## Task 6A: Pipeline-wide Top-level Graph Correction

**Deliverable:** 顶层命名和入口明确代表完整 RAG 管线；Query Rewrite 保持普通阶段而非子图。

- [x] 6A.1 RED：将测试改为要求 `RagState`、`build_rag_graph`、`test_rag_graph.py` 和 `rag` Studio 注册。
- [x] 6A.2 Verify RED：相关测试 Exit 1，8 个失败证明顶层仍被 Query Rewrite 命名锁定。
- [x] 6A.3 GREEN：重命名顶层 state/builder/Studio 及测试，node 直接读写共享 `RagState`。
- [x] 6A.4 Verify GREEN：Query Rewrite 阶段、RAG Graph 和 Studio 测试 Exit 0，32 passed。
- [x] 6A.5 REFACTOR：确认无 Query Rewrite 顶层 Graph/Studio/state 标识残留，也未引入子图。
- [x] 6A.6 Commit：`refactor(rag): make graph root pipeline-wide`。

## Task 6B: Minimal Query Rewrite State

**Deliverable:** Query Rewrite 成功或失败都只更新一个 `standalone_query`，不维护状态、失败码或 warnings。

- [x] 6B.1 RED：测试先禁止 `warnings`，Exit 1，8 个失败证明 warning 契约仍存在。
- [x] 6B.2 RED：进一步禁止 status 和 failure code，Exit 1，7 个失败证明诊断字段仍存在。
- [x] 6B.3 GREEN：删除相关枚举、常量、state channels 和 node 输出字段。
- [x] 6B.4 Verify GREEN：Query Rewrite、RAG Graph 和 Studio 相关测试 Exit 0，32 passed。
- [x] 6B.5 REFACTOR：确认 fallback 仍只调用模型一次、取消不被吞掉、输出只包含 `standalone_query`。
- [x] 6B.6 Commit：`refactor(rag): minimize query rewrite state`。

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
