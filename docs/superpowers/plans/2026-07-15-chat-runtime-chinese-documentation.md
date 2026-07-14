# Chat Runtime Chinese Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为生产 Chat/LangGraph 核心链路补充略详细的中文 docstring、分步骤注释和关键设计原因说明。

**Architecture:** 只修改注释和 docstring，不改变任何接口、类型、控制流或配置。注释集中在事务、资源生命周期、SSE producer、checkpoint 与 keyset pagination 等不直观边界，简单 DTO 和机械字段映射保持简洁。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、LangGraph、pytest。

## Global Constraints

- 用户已明确允许本次纯文档改动跳过 TDD，不新增文档结构测试。
- 不实现 OpenSpec 未声明的 stop、archive、concurrency、idempotency、heartbeat 或 replay 功能。
- 不修改 API schema、SSE payload、数据库表、异常语义或资源释放顺序。
- 使用中文解释职责和原因，不逐行翻译代码。

---

### Task 1: Producer 与 API 生命周期说明

**Files:**
- Modify: `backend/app/domains/chat/services/runtime.py`
- Modify: `backend/app/services/chat_api/deps.py`
- Modify: `backend/app/services/chat_api/router.py`
- Modify: `backend/app/services/chat_api/streaming.py`

**Interfaces:**
- Consumes: 现有 `CompletionProducer`、`CompletionProducerRegistry`、`ChatApiDeps`、completion/query routes 和 SSE adapter。
- Produces: 不改变接口；仅增加中文维护说明。

- [x] **Step 1: 补充类和函数 docstring**

为 channel、subscriber、registry、producer、lifespan、route 和 SSE adapter 说明职责、输入输出、失败边界与明确非职责。例如 producer 的说明必须包含：metadata 先发、Graph 增量透传、ASSISTANT 提交后才 completed、失败只发 error。

- [x] **Step 2: 为有顺序约束的流程添加步骤注释**

在 `CompletionProducer.run()`、`CompletionProducerRegistry.shutdown()`、`application_lifespan_resources()` 和 `create_completion()` 中使用下列语义的步骤注释：

```python
# 步骤 1：先发布 metadata，使调用方在模型运行前获得稳定业务 ID。
# 步骤 2：消费 Graph 流并在内存中拼接最终回答。
# 步骤 3：仅在 ASSISTANT 事务提交后发布 completed。
```

明确 subscriber detach 只停止入队，不取消后台 producer。

- [x] **Step 3: 运行核心 API 与 producer 回归（21 passed）**

Run: `cd backend && uv run python -m pytest tests/test_chat_completion_producer.py tests/test_chat_completion_disconnect.py tests/test_chat_api_lifespan.py tests/test_chat_completion_api.py tests/test_chat_sse_adapter.py -q`

Expected: 全部通过，行为无变化。

### Task 2: 业务事务、repository 与 Graph 边界说明

**Files:**
- Modify: `backend/app/domains/chat/services/conversation.py`
- Modify: `backend/app/domains/chat/repositories/conversation_repository.py`
- Modify: `backend/app/domains/chat/repositories/message_repository.py`
- Modify: `backend/app/domains/chat/graph/builder.py`
- Modify: `backend/app/domains/chat/graph/context.py`
- Modify: `backend/app/domains/chat/graph/state.py`
- Modify: `backend/app/domains/chat/graph/nodes/llm.py`
- Modify: `backend/app/infrastructure/langgraph.py`

**Interfaces:**
- Consumes: 现有 conversation/message repositories、`ConversationService`、Chat Graph 和 PostgreSQL saver。
- Produces: 不改变接口；说明业务表与 checkpoint 的分工、owner scope、cursor 方向和连接池生命周期。

- [x] **Step 1: 补充事务与分页说明**

说明 `accept_user_turn()` 在同一事务创建/校验会话并写入 USER 消息；会话 cursor 按 `(updated_at DESC, id DESC)` 向后翻页，消息 cursor 按 `(created_at ASC, id ASC)` 向后翻页；所有读取附加 user owner 条件，且不从 checkpoint 构造业务历史。

- [x] **Step 2: 补充 Graph 与 checkpoint 说明**

说明 Graph 只声明 `START -> llm -> END`，模型由 runtime context 注入；checkpointer 使用独立 psycopg pool、复用唯一 `DATABASE_URL`，进入上下文时执行 `setup()`，退出时始终关闭 pool。

- [x] **Step 3: 运行领域与基础设施回归（21 passed）**

Run: `cd backend && uv run python -m pytest tests/test_chat_conversation_service.py tests/test_chat_repositories.py tests/test_chat_graph.py tests/test_chat_langgraph_infrastructure.py -q`

Expected: 全部通过，行为无变化。

### Task 3: 全量验证与提交

**Files:**
- Modify: `docs/superpowers/plans/2026-07-15-chat-runtime-chinese-documentation.md`

**Interfaces:**
- Consumes: Task 1 和 Task 2 的纯注释改动。
- Produces: 已验证且可审阅的中文代码文档增强提交。

- [x] **Step 1: 检查差异仅包含注释/docstring**

Run: `git diff --word-diff=porcelain -- backend/app/domains/chat backend/app/services/chat_api backend/app/infrastructure/langgraph.py`

Expected: 不出现可执行语句、签名或配置变化。

- [x] **Step 2: 运行全部 Chat 测试（79 passed, 1 skipped）**

PowerShell Run: `$files = Get-ChildItem backend/tests -Filter 'test_chat_*.py' | ForEach-Object FullName; Push-Location backend; uv run python -m pytest @files -q; Pop-Location`

Expected: 全部通过或仅保留既有环境跳过项。

- [x] **Step 3: 运行完整后端与 OpenSpec 验证（484 passed, 3 skipped；strict valid）**

Run: `make test-backend`

Expected: 全部通过或仅保留既有环境跳过项。

Run: `openspec validate add-production-chat-langgraph-runtime --strict`

Expected: `Change 'add-production-chat-langgraph-runtime' is valid`。

- [x] **Step 4: 提交改动**

```powershell
git add backend/app/domains/chat backend/app/services/chat_api backend/app/infrastructure/langgraph.py docs/superpowers/plans/2026-07-15-chat-runtime-chinese-documentation.md
git commit -m "docs(chat): explain runtime control flow"
```
