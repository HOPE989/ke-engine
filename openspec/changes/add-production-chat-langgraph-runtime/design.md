## Context

项目已经通过 `chat-conversation-persistence` 建立 `conversations` 与 `messages` 两张业务表，但当前没有 Chat API、LangGraph 运行时或 SSE 输出链路。本变更需要在不改变既有表结构的前提下，形成一条生产级端到端链路；首版 Graph 只有一个 LLM 节点，但资源生命周期、故障语义、流协议和持久化边界不能按演示代码处理。

本设计以 `docs/my-specs/生产级Chat链路-LangGraph单节点运行时.md` 作为前期讨论草稿。实现方式参考 DeerFlow 的 `StateGraph + MessagesState + Graph stream + SSE adapter` 分层，以及 hope-agent 在首帧返回新会话 ID 的交互时序，但不复制它们与本项目约束不一致的取消、Graph 生命周期或 Agent Loop 行为。

关键约束如下：

- `conversations/messages` 是会话列表和用户可见消息历史的权威来源。
- LangGraph checkpoint 表只属于 runtime，由 LangGraph saver 自行管理，业务代码不通过 ORM、repository 或 Alembic 操作这些表。
- 用户主动停止与会话归档暂不实现；普通浏览器断开不能等价为停止。
- 进程崩溃或不可抗故障允许丢失当前节点最后一个 checkpoint 之后的 token，不做逐 token checkpoint。
- 首版不处理同一会话并发发送和请求幂等，调用方不得自动重试 completion POST。

## Goals / Non-Goals

**Goals:**

- 提供当前用户的会话列表、消息历史和流式 completion API。
- 发送首条消息时自动创建会话，并在 SSE 首事件返回会话 ID。
- 以 `START -> llm -> END` 建立最小但可扩展的 Chat Graph。
- 使用 PostgreSQL checkpointer 保存 LangGraph superstep，使同一会话后续轮次能够读取 Graph 上下文。
- 明确成功、节点失败、客户端断开和进程崩溃时业务表与 checkpoint 的一致性边界。
- 将模型、数据库连接池、checkpointer 和编译后 Graph 纳入 FastAPI 生命周期管理。

**Non-Goals:**

- 用户主动停止、部分回答归档和会话归档。
- RAG 检索、工具调用、多节点路由、人工中断或审批。
- 同一会话并发生成、请求幂等键和服务端自动重试。
- SSE token 重放、`Last-Event-ID`、心跳和断线续传。
- 崩溃后的后台扫描、任务恢复或业务表/checkpoint 对账修复。
- LangGraph Studio/CLI 的开发入口；需要时另建模块级开发 Graph。

## Decisions

### 1. 分离业务历史与 LangGraph runtime 状态

业务 API 只从 `conversations/messages` 读取用户可见历史；Graph 只通过 `AsyncPostgresSaver` 读写 checkpoint。两类数据复用同一个 PostgreSQL 实例，但使用两个独立连接池：现有 SQLAlchemy asyncpg pool 服务业务事务，psycopg async pool 服务 LangGraph saver。

这样可以保留 LangGraph 原生 checkpoint 行为，同时避免业务逻辑依赖其内部表结构。备选方案是把 checkpoint 当作消息历史，或自行维护 LangGraph 表；前者无法稳定支持业务查询与权限，后者会破坏 runtime 封装，均不采用。

`DATABASE_URL` 继续作为唯一数据库配置。创建 psycopg pool 时通过 SQLAlchemy URL 解析并生成兼容 DSN，不做脆弱的字符串替换。生产启动时 saver 初始化或建表失败即启动失败，不回退 `MemorySaver`。

### 2. Graph builder 与编译、生命周期分离

Graph 定义位于 Chat domain，使用 `MessagesState`（可通过空子类 `ChatState` 固化领域名称），稳定节点名为 `llm`，拓扑固定为：

```text
START -> llm -> END
```

builder 只声明 state、node 和 edge；生产 Graph 在 Chat API 的 FastAPI lifespan 中，待模型和 checkpointer 就绪后编译，并通过应用依赖注入给请求处理层。关闭时依次停止接收新请求并释放 saver pool 等资源。

不采用模块导入时编译的可变全局 Graph，因为生产资源无法可靠绑定和关闭。DeerFlow 的模块级入口同时服务 LangGraph 开发工具；若本项目未来需要 Studio/CLI，将增加独立 dev entrypoint，而不改变生产生命周期。

### 3. 模型通过 LangGraph runtime context 注入

`llm` node 从 runtime context 获取已构造的 ChatModel，接收 state messages 并返回完整 `AIMessage`。节点本身不读取全局 settings、不创建模型，也不持有连接资源。服务端使用 `OPENAI_MODEL` 确定模型，completion 请求不开放任意模型选择。

该选择使节点可用 fake model 做确定性测试，也为后续不同 runtime context 扩展留出边界。首版不为 LLM node 配置 LangGraph 自动重试，避免第一次尝试已经向客户端发送部分 token 后，重试输出与其混合。

### 4. 会话 ID 同时作为 LangGraph thread_id

后端 Snowflake 生成的 conversation ID 是唯一会话标识，并以十进制字符串写入 LangGraph configurable `thread_id`；不在业务表增加第二个 thread 字段，也不把 thread_id 放进 Graph state。所有 BIGINT ID 在 JSON/SSE 边界均编码为字符串，避免 JavaScript 精度损失。

同一 conversation 的后续请求使用相同 thread_id，从最后成功 checkpoint 继续；不同 conversation 的 checkpoint 必须隔离。

### 5. 先提交业务输入，再开启 Graph 事件流

`POST /api/v1/chat/completions` 收到请求后先验证当前用户的会话所有权。若未传 conversation ID，则在同一个业务事务中创建会话和首条 USER 消息；若已传，则追加 USER 消息并更新会话时间。事务提交后才构造 SSE 响应的运行任务。

SSE 首事件由应用生成 `metadata`，包含 `conversation_id` 和 `user_message_id`。随后开始消费 Graph 的 `astream_events()`，由适配层把 LangGraph 内部事件投影为稳定的 `content_delta` 事件，而不直接暴露框架事件结构。

成功时，producer 汇总完整回答，以 USER 消息为 parent 保存 ASSISTANT 消息；只有业务事务提交成功后才发送 `completed`。Graph、模型或持久化异常发送 `error`，且绝不发送 `completed`。因此 `completed` 是客户端可依赖的业务落库确认，而不是单纯的模型结束信号。

### 6. SSE producer 与客户端 subscriber 解耦

每个 completion 创建受应用管理的 producer task。SSE 响应是该任务的一个 subscriber：连接存在时接收 `metadata`、delta 和终态事件；浏览器普通断开时只解除订阅，不取消 producer。producer 继续消费 `astream_events()` 并在成功后持久化完整 ASSISTANT 消息。

subscriber 消失后 producer 不再把 token 放入无人消费的队列，只保留组成最终消息所需的内存缓冲，避免慢性队列增长。首版不跨进程保存流事件，因此不提供 token 重放或断线续传。

直接在 `StreamingResponse` 迭代器里运行并在断开时取消 Graph 的方案实现更简单，但会把网络状态错误地解释为用户停止，并导致回答无法落库，故不采用。

### 7. 失败以 LangGraph superstep 为一致性边界

LangGraph 节点只有正常返回后，其输出才进入 state 并形成后续 checkpoint。若 `llm` node 抛出异常，已经流出的部分 token 不构成有效 `AIMessage`；业务表也不保存 ASSISTANT 消息。当前 USER 消息已经提交，checkpoint 保持在最近一次成功 superstep，LangGraph 内部可能记录失败 provenance，但业务层不读取或修复它。

若服务进程在节点执行期间崩溃，当前节点最后一个成功 checkpoint 之后的 token 与未提交 ASSISTANT 消息同时丢弃。首版不扫描恢复，也不逐 token checkpoint；这是明确接受的故障窗口，而不是业务表与 Graph 的不一致。

### 8. API 与模块边界

目标模块边界如下，实际实施可在不改变职责的前提下合并过小文件：

```text
backend/app/contracts/chat/             HTTP 与 SSE DTO
backend/app/domains/chat/graph/          state、builder、llm node
backend/app/domains/chat/repositories/   conversation/message 数据访问
backend/app/domains/chat/services/       会话用例与 Graph runtime 编排
backend/app/infrastructure/langgraph.py  saver pool 与 checkpointer 生命周期
backend/app/services/chat_api/           FastAPI app、依赖、路由、SSE 适配
backend/app/entrypoints/chat_api.py       服务入口
```

会话列表和消息历史使用 cursor pagination。repository 的所有会话读取都带当前 Principal 的 user ID；不存在或不属于当前用户的会话统一返回 404，避免泄露资源存在性。

## Risks / Trade-offs

- [浏览器断开后任务仍消耗模型额度] → 这是保留完整回答的预期语义；通过任务注册、生命周期关闭和指标记录约束资源泄漏，主动停止另立变更实现。
- [单进程内 producer registry 无法跨进程恢复] → 明确接受进程崩溃丢失当前节点输出，终态只在当前连接可见，业务历史以已提交消息为准。
- [同一会话并发请求导致 checkpoint 竞争或消息顺序歧义] → 首版由客户端串行发送，服务端不宣称支持并发；后续基于实际需求增加会话级互斥或幂等协议。
- [SSE 已发送 delta 后最终持久化失败] → 发送 `error` 且不发送 `completed`；客户端只把 `completed` 视为已落库确认。
- [应用关闭时仍有后台 producer] → lifespan 停止阶段先拒绝新请求，给予在途任务有限的优雅完成窗口，再取消剩余任务并关闭连接池。
- [LangGraph 内部表未来升级] → 仅使用官方 saver API 和 `setup()`，不通过 Alembic 或业务 SQL 耦合内部 schema。
- [没有心跳时中间设备可能关闭长连接] → 首版模型首 token 延迟预计较短且已有成熟部署经验；若观测到空闲超时，再以独立规格增加心跳。

## Migration Plan

1. 增加 LangGraph、PostgreSQL saver 与 psycopg pool 依赖及配置校验。
2. 建立 saver/model 生命周期和最小 Graph，并完成 PostgreSQL checkpoint 集成测试。
3. 实现 repository、会话查询 API 与 completion 编排。
4. 接入 SSE 适配与后台 producer，覆盖成功、失败和断连测试。
5. 部署时由 saver `setup()` 创建或升级内部 checkpoint 表，再启动 Chat API；现有业务表无 Alembic 迁移。
6. 回滚时停止 Chat API 入口并回退应用版本；保留 LangGraph 内部表和业务消息，不做破坏性数据回滚。

## Open Questions

无阻塞实施的问题。用户主动停止、会话归档、并发控制、幂等、心跳和断线续传均明确留给后续独立变更。
