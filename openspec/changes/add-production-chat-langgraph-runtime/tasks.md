# Production Chat LangGraph Runtime TDD Implementation Plan

> 执行者必须逐项完成每个垂直切片的 RED → GREEN → REFACTOR → COMMIT；禁止先批量编写生产代码，再补测试。

**Goal:** 建立首版生产级 Chat 链路：当前用户会话 API、`START -> llm -> END` Graph、PostgreSQL checkpoint，以及 metadata-first 的 SSE completion。

**Architecture:** `conversations/messages` 继续作为用户可见历史的权威来源；LangGraph `AsyncPostgresSaver` 只管理 runtime checkpoint。FastAPI lifespan 负责业务数据库、模型、psycopg pool、checkpointer、编译后 Graph 和后台 completion producer 的创建与关闭。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy asyncio、LangChain、LangGraph、`langgraph-checkpoint-postgres`、psycopg 3、PostgreSQL、pytest、pytest-asyncio、httpx。

## Global TDD Constraints

- 每个 RED 步骤只引入当前切片的测试，不得顺带实现生产代码。
- 每个 RED 验证必须因目标行为缺失而失败；导入错误、fixture 错误或环境错误不算有效 RED，除非该切片本身就在驱动模块或依赖的创建。
- 每个 GREEN 只实现让当前测试通过的最小行为，不提前实现后续切片。
- 每个 REFACTOR 必须保持当前切片及所有既有 Chat 测试通过。
- 单元/API 测试使用 fake model、fake graph 或 fake repository，不访问真实 OpenAI 服务。
- 只有标记为 PostgreSQL integration 的测试访问本地 PostgreSQL；运行前使用 `docker compose up -d postgres`，不得清空现有业务库。
- 所有 BIGINT ID 在 HTTP/SSE 边界使用十进制字符串；Graph `thread_id` 直接使用 conversation ID 的十进制字符串。
- `conversations/messages` 是业务权威数据；任何业务测试和实现不得读取或修改 LangGraph 内部表。
- 普通浏览器断开只解除订阅，不取消 producer；主动停止、归档、并发、幂等、心跳、token replay 和自动恢复不在本变更实现。
- 每次提交前运行该切片的精确测试命令；最终再运行全量测试和 OpenSpec strict validation。

## 1. Dependency, configuration, contract, and layout baseline

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Create: `backend/app/contracts/chat/__init__.py`
- Create: `backend/app/contracts/chat/http.py`
- Create: `backend/app/contracts/chat/stream.py`
- Test: `backend/tests/test_chat_contracts.py`
- Test: `backend/tests/test_chat_config.py`
- Modify: `backend/tests/test_target_architecture_layout.py`

**Interfaces:** `CompletionRequest(conversation_id: str | None, content: str)`；会话/消息 page DTO；`MetadataPayload`、`ContentDeltaPayload`、`CompletedPayload`、`ErrorPayload`；`Settings.openai_model` 是 Chat API 启动必需但其他进程仍可不配置的 startup-only 字段。

- [x] 1.1 RED — 添加 contract/config/layout 测试：空白 content 校验失败、conversation ID 只接受十进制字符串、所有响应 ID 序列化为字符串、completion 输入不包含 `model`、四种 SSE payload 字段固定、本切片新增的 Chat contract 路径被架构测试声明。
- [x] 1.2 RED VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_contracts.py tests/test_chat_config.py tests/test_target_architecture_layout.py -q`；预期因 Chat contracts/目标模块尚不存在或依赖尚未安装而失败，不接受测试收集本身写错。
- [x] 1.3 GREEN — 使用 `uv add langgraph langgraph-checkpoint-postgres "psycopg[binary,pool]"` 更新依赖与 lockfile；创建最小 Pydantic contracts；把 `openai_model` 加入 `STARTUP_ONLY_SETTINGS`，并提供 Chat 启动期显式校验函数，避免 Document API 因未配置模型而启动失败。
- [x] 1.4 GREEN VERIFY — 重跑 1.2 的精确命令；预期全部通过。
- [x] 1.5 REFACTOR — 去除 contracts 中重复的 ID 转换和字段定义，但不建立通用 transport 大目录；运行 `cd backend && uv run python -m pytest tests/test_chat_contracts.py tests/test_chat_config.py tests/test_target_architecture_layout.py tests/test_project_layout.py -q`。
- [x] 1.6 COMMIT — 提交上述文件，提交信息：`feat(chat): define runtime dependencies and contracts`。

## 2. Minimal Chat Graph and injected model

**Files:**
- Create: `backend/app/domains/chat/graph/__init__.py`
- Create: `backend/app/domains/chat/graph/state.py`
- Create: `backend/app/domains/chat/graph/context.py`
- Create: `backend/app/domains/chat/graph/builder.py`
- Create: `backend/app/domains/chat/graph/nodes/__init__.py`
- Create: `backend/app/domains/chat/graph/nodes/llm.py`
- Test: `backend/tests/test_chat_graph.py`

**Interfaces:** `ChatState(MessagesState)`；`ChatRuntimeContext(model: BaseChatModel)`；`async llm_node(state: ChatState, runtime: Runtime[ChatRuntimeContext]) -> dict[str, list[BaseMessage]]`；`build_chat_graph() -> StateGraph` 返回未编译 builder，稳定节点名为 `llm`。

- [x] 2.1 RED — 在 `test_chat_graph.py` 添加单一切片测试：Graph 只有 `START -> llm -> END`；fake model 收到 state messages；节点返回的 `AIMessage` 通过 `MessagesState` 合并；导入模块不创建模型、不读 settings、不打开数据库；节点没有 retry policy。
- [x] 2.2 RED VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_graph.py -q`；预期因 graph 模块和接口尚不存在而失败。
- [x] 2.3 GREEN — 实现 `ChatState`、runtime context、最小 `llm_node` 和 builder；只满足单节点图与注入模型，不加入 checkpoint、SSE、重试或业务持久化。
- [x] 2.4 GREEN VERIFY — 重跑 2.2 命令；预期全部通过。
- [x] 2.5 REFACTOR — 固定公开 import 和节点常量，消除 builder 与 node 的循环依赖；运行 `cd backend && uv run python -m pytest tests/test_chat_graph.py tests/test_target_architecture_layout.py -q`。
- [x] 2.6 COMMIT — 提交 Graph 与测试，提交信息：`feat(chat): add minimal langgraph topology`。

## 3. PostgreSQL checkpointer resource

**Files:**
- Create: `backend/app/infrastructure/langgraph.py`
- Test: `backend/tests/test_chat_langgraph_infrastructure.py`

**Interfaces:** `to_psycopg_dsn(database_url: str) -> str` 使用 SQLAlchemy URL 解析；`postgres_checkpointer(database_url: str)` 是 async context manager，内部创建独立 `AsyncConnectionPool`，以 `autocommit=True`、`dict_row` 连接参数构造 `AsyncPostgresSaver`，进入时执行 `await saver.setup()`，退出时关闭 pool。

- [x] 3.1 RED — 添加 DSN 转换测试，覆盖 `postgresql+asyncpg://`、已转义用户名/密码、query 参数和非法非 PostgreSQL URL；添加 fake pool/saver 生命周期测试，断言 pool 与业务 SQLAlchemy engine 无共享、`setup()` 恰好一次、异常时也关闭 pool。
- [x] 3.2 RED VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_langgraph_infrastructure.py -q`；预期因 `app.infrastructure.langgraph` 尚不存在而失败。
- [x] 3.3 GREEN — 实现 URL 转换和 async context manager；只使用 LangGraph saver 公开 API，不定义 checkpoint ORM model，不新增 Alembic migration，不提供 `InMemorySaver` fallback。
- [x] 3.4 GREEN VERIFY — 重跑 3.2 命令；预期全部通过。
- [x] 3.5 REFACTOR — 把 pool 构造保留为可 monkeypatch 的小函数并收紧类型；运行 `cd backend && uv run python -m pytest tests/test_chat_langgraph_infrastructure.py tests/test_chat_graph.py -q`。
- [x] 3.6 COMMIT — 提交基础设施与测试，提交信息：`feat(chat): add postgres checkpoint resource`。

## 4. Chat API lifespan and production Graph compilation

**Files:**
- Create: `backend/app/services/chat_api/__init__.py`
- Create: `backend/app/services/chat_api/deps.py`
- Create: `backend/app/services/chat_api/app.py`
- Create: `backend/app/entrypoints/chat_api.py`
- Test: `backend/tests/test_chat_api_lifespan.py`
- Modify: `backend/tests/test_service_entrypoints.py`

**Interfaces:** `ChatApiDeps(session_factory, id_generator, graph, model, producer_registry)` 存于 `app.state.chat_deps`；`application_lifespan_resources(application, settings)` 按数据库 → 模型 → checkpointer → Graph → producer registry 顺序初始化，按相反顺序释放；`create_app() -> FastAPI`；entrypoint 导出 `app`。

- [x] 4.1 RED — 添加 lifespan 测试，使用 fakes 记录初始化/关闭顺序，断言 Graph 只在 model 和 saver 就绪后编译、依赖挂载到 `app.state`、关闭时先处理 producer 再关闭 saver；模型或 saver 初始化异常必须让启动失败且不得创建内存 saver。
- [x] 4.2 RED VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_api_lifespan.py tests/test_service_entrypoints.py -q`；预期因 Chat API app/deps/entrypoint 尚不存在而失败。
- [x] 4.3 GREEN — 按现有 Document API 的 `AsyncExitStack` 模式实现 Chat lifespan、依赖访问器、app factory、健康检查和 entrypoint；生产 Graph 只在 lifespan 内编译。
- [x] 4.4 GREEN VERIFY — 重跑 4.2 命令；预期全部通过。
- [x] 4.5 REFACTOR — 复用现有数据库 session 初始化方式，但保持 Chat 与 Document API 的资源集合独立；运行 `cd backend && uv run python -m pytest tests/test_chat_api_lifespan.py tests/test_service_entrypoints.py tests/test_document_async_infrastructure.py -q`。
- [x] 4.6 COMMIT — 提交生命周期与测试，提交信息：`feat(chat): assemble lifespan-managed graph runtime`。

## 5. Owned conversation and message queries

**Files:**
- Create: `backend/app/domains/chat/repositories/__init__.py`
- Create: `backend/app/domains/chat/repositories/conversation_repository.py`
- Create: `backend/app/domains/chat/repositories/message_repository.py`
- Test: `backend/tests/test_chat_repositories.py`

**Interfaces:** repositories 接收当前 `AsyncSession`；`ConversationCursor(updated_at, id)` 与 `MessageCursor(created_at, id)` 编解码为 opaque cursor；conversation 查询始终包含 `user_id` 和非 DELETED 约束；message 查询先通过 owner-scoped conversation 条件限制。

- [x] 5.1 RED — 添加 repository 测试：会话按 `(updated_at DESC, id DESC)` keyset 分页、消息按 `(created_at ASC, id ASC)` keyset 分页、第二页无重复/遗漏、他人会话不可见、历史 SQL 只读业务表且不引用 checkpoint 表名。
- [x] 5.2 RED VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_repositories.py -q`；预期因 repository 和 cursor 接口尚不存在而失败。
- [x] 5.3 GREEN — 实现 owner-scoped repository 查询和 cursor 编解码；不引入 offset pagination，不读取 LangGraph saver。
- [x] 5.4 GREEN VERIFY — 重跑 5.2 命令；预期全部通过。
- [x] 5.5 REFACTOR — 抽取每个 repository 内部的 cursor predicate，保留会话与消息不同排序方向；运行 `cd backend && uv run python -m pytest tests/test_chat_repositories.py tests/test_chat_persistence.py -q`。
- [x] 5.6 COMMIT — 提交查询 repository 与测试，提交信息：`feat(chat): query owned conversations and messages`。

## 6. Transactional user-turn acceptance

**Files:**
- Create: `backend/app/domains/chat/services/__init__.py`
- Create: `backend/app/domains/chat/services/conversation.py`
- Test: `backend/tests/test_chat_conversation_service.py`

**Interfaces:** `AcceptedUserTurn(conversation_id: int, user_message_id: int, content: str)`；`ConversationService.accept_user_turn(user_id: str, content: str, conversation_id: int | None) -> AcceptedUserTurn`；新会话与 USER 消息在同一 `session.begin()` 中提交，现有会话先 owner-scoped 查询再追加并更新 `updated_at`。

- [x] 6.1 RED — 添加 service 测试：无 conversation ID 时创建 ACTIVE 会话并从规范化首条消息截取 255 字符标题；有 ID 时追加到本人会话；空白 content 在开启事务前拒绝；不存在或他人会话产生同一 not-found 领域错误；conversation 与 USER message 任一写入失败时整笔回滚。
- [x] 6.2 RED VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_conversation_service.py -q`；预期因 conversation service 尚不存在而失败。
- [x] 6.3 GREEN — 使用现有 Snowflake generator、models 和 repositories 实现最小事务服务；返回值只包含启动 Graph 所需的稳定输入，不启动 Graph、不创建 SSE。
- [x] 6.4 GREEN VERIFY — 重跑 6.2 命令；预期全部通过。
- [x] 6.5 REFACTOR — 将标题规范化和 ID 分配保持为纯函数/注入依赖，减少事务测试的时钟耦合；运行 `cd backend && uv run python -m pytest tests/test_chat_conversation_service.py tests/test_chat_repositories.py tests/test_chat_persistence.py -q`。
- [x] 6.6 COMMIT — 提交用户轮次事务与测试，提交信息：`feat(chat): persist accepted user turns atomically`。

## 7. Application-owned SSE event adapter

**Files:**
- Create: `backend/app/services/chat_api/streaming.py`
- Test: `backend/tests/test_chat_sse_adapter.py`

**Interfaces:** `encode_sse(event: str, payload: BaseModel) -> bytes`；`project_graph_event(event: dict[str, object]) -> ContentDeltaPayload | None`；只把 LLM message chunk 文本投影成 `content_delta`，其他 lifecycle/diagnostic 事件返回 `None`。

- [x] 7.1 RED — 添加 adapter 测试：事件名与 JSON data 使用合法 SSE 帧；多个 text chunk 顺序不变；空 chunk 和非公开 LangGraph 事件被忽略；payload 不泄露 `event/name/run_id/tags/metadata` 等内部字段；metadata/completed/error 编码字段固定。
- [x] 7.2 RED VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_sse_adapter.py -q`；预期因 streaming adapter 尚不存在而失败。
- [x] 7.3 GREEN — 实现最小 SSE 编码和 `astream_events()` 事件投影纯函数，不加入 heartbeat、event ID 或 replay storage。
- [x] 7.4 GREEN VERIFY — 重跑 7.2 命令；预期全部通过。
- [x] 7.5 REFACTOR — 将框架事件识别集中在 adapter 内，producer 不解析 LangGraph 原始结构；运行 `cd backend && uv run python -m pytest tests/test_chat_sse_adapter.py tests/test_chat_contracts.py -q`。
- [x] 7.6 COMMIT — 提交 SSE adapter 与测试，提交信息：`feat(chat): project graph events to sse`。

## 8. Completion producer success path

**Files:**
- Create: `backend/app/domains/chat/services/runtime.py`
- Test: `backend/tests/test_chat_completion_producer.py`

**Interfaces:** `CompletionProducer.run(turn: AcceptedUserTurn, user_id: str) -> None`；调用 compiled graph 的 `astream_events()`，input 只含当前 USER message，config 使用 `{"configurable": {"thread_id": str(conversation_id)}}`，context 注入 model；producer 汇总 text chunk，通过 message repository 保存 ASSISTANT 后发布 `completed`。

- [x] 8.1 RED — 添加成功路径测试：metadata 在 graph 开始前发布；Graph 收到十进制 string thread ID；delta 保持顺序；完整 ASSISTANT 以 USER message 为 parent 保存；只有保存事务提交后才发布含 string `assistant_message_id` 和 `finish_reason=stop` 的 `completed`；成功后不发布 `error`。
- [x] 8.2 RED VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_completion_producer.py -k success -q`；预期因 completion runtime 尚不存在而失败。
- [x] 8.3 GREEN — 实现只覆盖成功路径的 producer、单 subscriber 发布接口和 ASSISTANT 持久化；不实现失败吞吐、断连优化或进程恢复。
- [x] 8.4 GREEN VERIFY — 重跑 8.2 命令；预期全部通过。
- [x] 8.5 REFACTOR — 分离 Graph event consumption、answer accumulation 和 ASSISTANT commit 三个私有步骤；运行 `cd backend && uv run python -m pytest tests/test_chat_completion_producer.py -k success tests/test_chat_sse_adapter.py -q`。
- [x] 8.6 COMMIT — 提交成功 producer 与测试，提交信息：`feat(chat): persist successful streamed completions`。

## 9. Completion producer failure boundary

**Files:**
- Modify: `backend/app/domains/chat/services/runtime.py`
- Modify: `backend/tests/test_chat_completion_producer.py`

**Interfaces:** producer 的公开接口保持不变；异常统一投影成一个 `error` terminal event；只有 ASSISTANT commit 成功才能发布 `completed`。

- [x] 9.1 RED — 增加失败路径测试：Graph 在部分 delta 后抛错时 USER 保留、ASSISTANT 不写入、发布一个 `error` 且无 `completed`；ASSISTANT commit 失败时同样只发 `error`；不得自动第二次调用 Graph；错误事件不得暴露堆栈、DSN 或密钥。
- [x] 9.2 RED VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_completion_producer.py -k "failure or error" -q`；预期新增断言失败，同时既有 success 测试继续通过。
- [x] 9.3 GREEN — 在 producer 最小增加异常终态和敏感信息隔离；不保存部分 ASSISTANT，不给 LLM node 增加 retry policy，不修改 checkpoint 内部表。
- [x] 9.4 GREEN VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_completion_producer.py -q`；预期成功和失败测试全部通过。
- [x] 9.5 REFACTOR — 用单一 terminal transition 防止 `completed/error` 双发；重跑 9.4 命令并确认 terminal 计数断言仍通过。
- [x] 9.6 COMMIT — 提交失败边界与测试，提交信息：`feat(chat): enforce completion failure boundary`。

## 10. Subscriber disconnect and producer registry

**Files:**
- Modify: `backend/app/domains/chat/services/runtime.py`
- Modify: `backend/app/services/chat_api/deps.py`
- Test: `backend/tests/test_chat_completion_disconnect.py`

**Interfaces:** `CompletionProducerRegistry.start(...)` 创建并持有 producer task；subscriber 使用有界/可解除的 queue；`detach()` 只移除 subscriber；`shutdown()` 停止接收新任务、等待有限优雅窗口后取消剩余任务。

- [x] 10.1 RED — 添加断连测试：subscriber 在首个 delta 后 detach，Graph task 未被取消并继续保存完整 ASSISTANT；detach 后不再向 queue 写 token；registry shutdown 按既定顺序等待 producer；新任务在 shutdown 开始后被拒绝。
- [x] 10.2 RED VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_completion_disconnect.py -q`；预期因 registry/detach 行为尚不存在而失败。
- [x] 10.3 GREEN — 实现 registry、subscriber detach 和无订阅时停止事件入队；producer 只保留最终回答 buffer，不实现跨进程恢复或 token replay。
- [x] 10.4 GREEN VERIFY — 重跑 10.2 命令；预期全部通过。
- [x] 10.5 REFACTOR — 集中 task ownership 和 shutdown 状态转换，避免请求协程直接拥有 Graph task；运行 `cd backend && uv run python -m pytest tests/test_chat_completion_disconnect.py tests/test_chat_completion_producer.py tests/test_chat_api_lifespan.py -q`。
- [x] 10.6 COMMIT — 提交断连与 registry，提交信息：`feat(chat): continue completions after subscriber disconnect`。

## 11. Conversation list and message-history HTTP API

**Files:**
- Create: `backend/app/services/chat_api/router.py`
- Modify: `backend/app/services/chat_api/app.py`
- Modify: `backend/app/services/chat_api/deps.py`
- Test: `backend/tests/test_chat_query_api.py`

**Interfaces:** `GET /api/v1/chat/conversations`；`GET /api/v1/chat/conversations/{conversation_id}/messages`；两者从 `Principal` 取得 user ID，通过 service/repository 读取业务表，使用 cursor/limit，missing 与 foreign-owned conversation 均映射为 404。

- [x] 11.1 RED — 添加 API 测试：会话 newest-first、消息 chronological、next cursor、全部 ID 为 string、只返回当前用户数据、missing/foreign 都是相同 404、fake checkpointer 若被读取立即让测试失败。
- [x] 11.2 RED VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_query_api.py -q`；预期因 Chat router 尚未提供查询端点而失败。
- [x] 11.3 GREEN — 实现两个查询端点、依赖装配和领域错误映射；只返回 contracts 定义字段，不从 checkpoint 组装历史。
- [x] 11.4 GREEN VERIFY — 重跑 11.2 命令；预期全部通过。
- [x] 11.5 REFACTOR — 复用当前身份依赖和统一响应约定，不复制 IdentityMiddleware；运行 `cd backend && uv run python -m pytest tests/test_chat_query_api.py tests/test_identity.py tests/test_document_status_query.py -q`。
- [x] 11.6 COMMIT — 提交查询 API 与测试，提交信息：`feat(chat): expose conversation query api`。

## 12. Metadata-first completion HTTP API

**Files:**
- Modify: `backend/app/services/chat_api/router.py`
- Modify: `backend/app/services/chat_api/streaming.py`
- Modify: `backend/app/services/chat_api/deps.py`
- Test: `backend/tests/test_chat_completion_api.py`

**Interfaces:** `POST /api/v1/chat/completions` 接收 `CompletionRequest`；先 `accept_user_turn()` 提交业务事务，再注册 producer 并返回 `StreamingResponse(media_type="text/event-stream")`；headers 包含 `Cache-Control: no-cache` 和 `X-Accel-Buffering: no`。

- [x] 12.1 RED — 添加 API 测试：首条消息自动创建会话；第一帧必为 metadata 且含 string conversation/user message ID；已有会话复用 ID；空白 content 不创建数据；foreign conversation 返回 404；headers 禁缓存/代理缓冲；请求 schema 不接受 model、幂等键或客户端 thread ID。
- [x] 12.2 RED VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_completion_api.py -k "metadata or validation or ownership or headers" -q`；预期因 completion endpoint 尚不存在而失败。
- [x] 12.3 GREEN — 实现 completion route 和 metadata-first bridge；确保业务事务提交失败时不打开成功 SSE 流，metadata 发布后才允许 producer 调用 Graph。
- [x] 12.4 GREEN VERIFY — 重跑 12.2 命令；预期全部通过。
- [x] 12.5 RED — 增加流终态 API 测试：成功序列为 metadata → content_delta* → completed；Graph 或 ASSISTANT commit 失败为 metadata → content_delta* → error；两种终态互斥；流中无 heartbeat、SSE id 或 replay 声明。
- [x] 12.6 RED VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_completion_api.py -k "terminal or heartbeat or replay" -q`；预期新增终态测试失败。
- [x] 12.7 GREEN — 连接 route subscriber 与 producer terminal events，只实现当前连接的 live stream，不实现 `Last-Event-ID`、重连恢复或服务端自动 retry。
- [x] 12.8 GREEN VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_completion_api.py -q`；预期 completion API 测试全部通过。
- [x] 12.9 REFACTOR — 保持 route 只负责身份、输入、事务启动与 transport，Graph 编排继续位于 runtime service；运行 `cd backend && uv run python -m pytest tests/test_chat_completion_api.py tests/test_chat_query_api.py tests/test_chat_completion_producer.py -q`。
- [x] 12.10 COMMIT — 提交 completion API 与测试，提交信息：`feat(chat): expose metadata-first completion stream`。

## 13. Real PostgreSQL checkpoint integration

**Files:**
- Test: `backend/tests/test_chat_langgraph_postgres.py`
- Test: `backend/tests/test_chat_failure_consistency_postgres.py`
- Modify only if tests expose a defect: `backend/app/infrastructure/langgraph.py`
- Modify only if tests expose a defect: `backend/app/domains/chat/graph/builder.py`
- Modify only if tests expose a defect: `backend/app/domains/chat/services/runtime.py`

**Interfaces:** 使用本地 `DATABASE_URL` 和唯一测试 thread IDs；fake model 提供确定输出；测试只通过 saver/compiled Graph 公开 API 读取 state，不直接查询 checkpoint 表。

- [x] 13.1 RED — 启动 PostgreSQL：`docker compose up -d postgres`；添加 integration 测试，覆盖 `setup()`、同一 thread 两轮读取前轮消息、不同 thread 隔离、失败 node 的部分输出不成为完整 AIMessage、失败后可用 state 停留在最后成功 superstep。
- [x] 13.2 RED — 增加故障一致性 integration 测试：先提交 USER 业务消息，再让可控 fake model 发出部分 chunk 后阻塞；中止该次运行并使用同一 saver/thread 重新加载，断言部分 AIMessage 不存在、业务表只有 USER、系统没有自动恢复扫描或第二次模型调用。
- [x] 13.3 RED VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_chat_langgraph_postgres.py tests/test_chat_failure_consistency_postgres.py -m integration -q`；完整真实集成场景首次运行即通过，经用户明确许可不人为制造 RED。
- [x] 13.4 GREEN — integration 未暴露 saver、config、context、Graph 编译或 producer 边界缺陷，无需修改生产代码。
- [x] 13.5 GREEN VERIFY — 重跑 13.3 命令；预期全部通过，并确认没有真实 OpenAI 请求。
- [x] 13.6 REFACTOR — 将 integration fixture 的隔离 schema、thread ID、fake model 和资源清理集中到测试 fixture；运行 `cd backend && uv run python -m pytest tests/test_chat_langgraph_postgres.py tests/test_chat_failure_consistency_postgres.py tests/test_chat_langgraph_infrastructure.py tests/test_chat_graph.py -q`。
- [x] 13.7 COMMIT — 提交 PostgreSQL integration 测试及必要修复，提交信息：`test(chat): verify postgres checkpoint semantics`。

## 14. End-to-end regression, operability, and OpenSpec handoff

**Files:**
- Modify: `Makefile`
- Modify: `backend/.env.example`
- Modify: `backend/tests/test_backend_makefile.py`
- Modify: `backend/tests/test_target_architecture_layout.py`
- Modify: `backend/tests/test_service_entrypoints.py`

**Interfaces:** `make dev-chat-api` 启动 `app.entrypoints.chat_api:app`；环境样例包含 Chat model/API 配置和既有 `DATABASE_URL`，不新增第二个数据库 URL。

- [ ] 14.1 RED — 扩展 Makefile/entrypoint/layout 测试，断言存在 `dev-chat-api`、Chat entrypoint、目标模块和唯一数据库配置；断言没有 `domains/agent`、Chat checkpoint ORM/Alembic migration、MemorySaver production fallback 或新的 checkpoint database setting。
- [ ] 14.2 RED VERIFY — 运行 `cd backend && uv run python -m pytest tests/test_backend_makefile.py tests/test_target_architecture_layout.py tests/test_service_entrypoints.py -q`；预期因启动命令或最终布局尚未声明而失败。
- [ ] 14.3 GREEN — 增加 `CHAT_API_PORT` 与 `dev-chat-api` target，补齐环境样例和最终公开 imports；不启动实现范围外的 stop/archive/concurrency/idempotency/heartbeat/replay 功能。
- [ ] 14.4 GREEN VERIFY — 重跑 14.2 命令；预期全部通过。
- [ ] 14.5 REFACTOR VERIFY — 运行全部 Chat 测试：`cd backend && uv run python -m pytest tests/test_chat_*.py -q`；预期全部通过。
- [ ] 14.6 REGRESSION VERIFY — 运行完整后端测试：`make test-backend`；预期全部通过，无 Document/Identity 回归。
- [ ] 14.7 SPEC VERIFY — 运行 `openspec validate add-production-chat-langgraph-runtime --strict`；预期 `Change 'add-production-chat-langgraph-runtime' is valid`。
- [ ] 14.8 SCOPE VERIFY — 搜索并人工核对没有未授权实现：`rg -n "MemorySaver|Last-Event-ID|heartbeat|idempotency|archive|stop" backend/app backend/tests`；只允许规格否定测试、错误消息或既有无关代码命中。
- [ ] 14.9 COMMIT — 提交 operability 与最终验证调整，提交信息：`chore(chat): finalize runtime operability`。
