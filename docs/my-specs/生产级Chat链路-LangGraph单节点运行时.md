# 生产级单节点 Chat LangGraph 运行链路设计（讨论草稿）

> 本文档用于保留前期讨论结论，正式需求、设计与实施任务以对应的 OpenSpec change 为准。

## 背景

项目已经建立 `conversations` 与 `messages` 两张 Chat 业务表，但尚未提供会话 API、消息查询、LangGraph 运行时或流式回答。下一阶段不是制作一个仅验证 LangGraph API 的示例，而是建立可继续演进为 RAG Chat 的生产级端到端链路；第一版 Graph 拓扑暂时只有一个 LLM 节点。

本设计参考 DeerFlow 的 `StateGraph + MessagesState + Graph stream + SSE adapter` 分层方式，以及 hope-agent 首条消息自动创建会话并在流式首帧返回会话 ID 的交互时序。参考只用于确认成熟的边界和体验，不照搬其前端生成 thread ID、客户端断连取消任务、模块级可变 Graph 或自定义 Agent Loop。

## 目标

- 提供当前用户的会话列表和消息历史查询。
- 发送第一条消息时自动创建会话，已有会话继续追加消息。
- 使用 `START -> llm -> END` 的 LangGraph 处理对话。
- 使用 LangGraph `AsyncPostgresSaver` 保存 runtime checkpoint。
- 使用类型化 SSE 输出会话元数据、模型增量、正常完成或错误事件。
- 浏览器普通断连后 Graph 继续在当前服务进程内完成并保存最终回答。
- 保持业务消息与 LangGraph State 的成功、失败语义一致。
- 建立可支持后续 query rewrite、RAG、工具调用和条件路由的清晰模块边界。

## 非目标

- 不实现用户主动停止。
- 不实现会话归档。
- 不实现同一会话的并发运行控制。
- 不实现请求幂等键或自动重发。
- 不实现 SSE `Last-Event-ID` 精确续传或 token 事件持久化。
- 不实现进程崩溃后的扫描、自动恢复或对账。
- 不实现 RAG、工具调用、子图、路由或提示词管理。
- 不引入 LangGraph Agent Server。
- 不创建 `domains/agent` 或其他泛化 Agent 边界。

## 参考方案结论

### DeerFlow

DeerFlow 的生产 API 将 LangGraph 嵌入 FastAPI，通过 `graph.astream(...)` 获取 `messages` 和 `updates`，再投影为 `message_chunk`、`tool_calls`、`interrupt`、`citations` 等稳定 SSE 事件。其 `langgraph.json` 和模块级 Graph 同时服务 LangGraph dev server、Studio、CLI 和独立 workflow。

本项目吸收以下做法：

- State 继承 `MessagesState`。
- Builder 只声明节点和边。
- 节点返回 State 增量，不认识 HTTP 或 SSE。
- Graph 流事件经过 Adapter 后才成为前端协议。
- PostgreSQL checkpointer 由应用生命周期创建和关闭。

本项目不照搬以下做法：

- 不由前端生成 `thread_id`。
- 不在请求期间修改已编译全局 Graph 的 checkpointer。
- 不把浏览器断连解释为 Graph 取消。
- 不保存逐 token SSE 内容。
- 不使用 DeerFlow 当前较早期的流 API；新实现使用当前 LangGraph `astream_events()`，但维持相同的事件投影思想。

### hope-agent

hope-agent 在模型运行前创建并提交会话、持久化用户消息，然后先发送携带 `session_id` 的空增量首帧，再开始 Agent Loop。该时序已经验证首帧与后续 token 的体验连贯。

本项目采用相同时序，但把自定义 Agent Loop 替换为 LangGraph `astream_events()`，并把 `session_id` 改为后端业务表生成的 `conversation_id`。

## 总体架构

```text
Chat API
├─ 会话列表
├─ 消息历史
└─ 发送消息 + SSE Adapter
          │
          ▼
Chat Application Service
├─ 创建或校验 Conversation
├─ 持久化 User Message
├─ 启动后台 Graph producer
└─ Graph 成功后持久化 Assistant Message
          │
          ▼
Chat Graph
└─ START -> llm -> END
          │
          ├─ ChatOpenAI
          └─ AsyncPostgresSaver
```

建议目录：

```text
backend/app/
├─ contracts/chat/
│  ├─ __init__.py
│  ├─ http.py
│  └─ stream.py
├─ domains/chat/
│  ├─ graph/
│  │  ├─ __init__.py
│  │  ├─ builder.py
│  │  ├─ state.py
│  │  └─ nodes/
│  │     ├─ __init__.py
│  │     └─ llm.py
│  ├─ repositories/
│  │  ├─ __init__.py
│  │  ├─ conversation_repository.py
│  │  └─ message_repository.py
│  ├─ services/
│  │  ├─ __init__.py
│  │  ├─ conversation.py
│  │  └─ runtime.py
│  └─ shared/models.py
├─ infrastructure/
│  ├─ llm.py
│  └─ langgraph.py
├─ services/chat_api/
│  ├─ __init__.py
│  ├─ app.py
│  ├─ deps.py
│  ├─ router.py
│  └─ streaming.py
└─ entrypoints/chat_api.py
```

边界规则：

- `domains/chat/graph/` 只认识 Graph State、runtime context、节点和模型接口。
- Repository 只管理 `conversations/messages` 业务表。
- `infrastructure/langgraph.py` 管理 psycopg pool、`AsyncPostgresSaver` 的初始化和关闭。
- `domains/chat/services/runtime.py` 编排一次对话运行，不编码 HTTP SSE 文本。
- `services/chat_api/streaming.py` 把内部事件编码为 SSE。
- `conversation.id` 转成字符串后直接作为 LangGraph `thread_id`。

## Graph 设计

### State

第一版 State 直接继承 `MessagesState`：

```python
class ChatState(MessagesState):
    pass
```

`conversation_id`、ORM 对象、数据库 Session 和 HTTP 信息不进入 State。`thread_id` 通过 `RunnableConfig.configurable` 传递。

### Runtime context

模型通过 LangGraph runtime context 注入，不在节点内部读取全局 Settings 或创建 SDK client。Graph context 至少包含已初始化的 Chat model。

### Builder

Builder 工厂只声明稳定拓扑：

```text
START -> llm -> END
```

节点名固定为 `llm`。checkpoint 上线后，节点名属于持久化运行协议的一部分，不应随意修改。

Builder 与编译分离。生产 Graph 在 Chat API lifespan 中取得模型和 checkpointer 后执行 `compile(checkpointer=...)`。本次不导出模块级生产 Graph；未来确实需要 LangGraph Studio 或 CLI 时，新增独立开发入口，而不改变生产装配方式。

### LLM 节点

`llm` 节点：

- 从 `ChatState.messages` 读取完整 Graph 对话上下文。
- 通过 runtime context 使用注入的模型。
- 正常完成时返回 `{"messages": [AIMessage]}`。
- 不访问 Repository、ORM、SSE 或业务表。
- 不吞掉模型异常，也不把错误转换为伪成功 AIMessage。
- 第一版不配置 LangGraph 节点自动重试。流式输出部分 token 后重试会让客户端混合两次生成结果；在没有 token reset/去重协议前，失败应直接结束本次运行。

## 两个数据平面

### 业务数据平面

`conversations/messages` 是用户可见数据的权威来源，服务于：

- 会话列表；
- 消息历史；
- 用户归属；
- 最终可见 User/Assistant 消息；
- 后续 RAG 引用、模型名、token 统计和停止原因。

业务 API 不读取 LangGraph checkpoint 表生成列表或历史。

### LangGraph runtime 平面

LangGraph 内置 checkpoint 表由 `AsyncPostgresSaver` 独占管理，服务于：

- Graph State；
- superstep 进度；
- pending task；
- failure provenance；
- 同一 `thread_id` 的短期对话上下文。

应用不解析、不修改、不通过 Alembic 管理这些内置表。应用只负责创建 saver、调用官方 `setup()`、编译 Graph，并在运行配置中传入 `thread_id=str(conversation.id)`。

两个平面不追求表记录逐条对应，也不做跨表事务或对账。它们通过相同的对话语义保持一致：

- User Message 在进入 Graph 前写入业务表，同时作为本轮 Graph 输入。
- 节点正常完成后，AIMessage 进入 Graph State，并写入业务表。
- 节点异常或进程在节点执行中崩溃时，节点 buffered writes 不进入 Graph State，业务表也不写未完成 Assistant Message。

## API 设计

### 会话列表

```text
GET /api/v1/chat/conversations
```

只返回当前 Principal 拥有且未删除的会话。使用 `(updated_at DESC, id DESC)` 的不透明游标分页，默认页大小 20，最大 100。

### 消息历史

```text
GET /api/v1/chat/conversations/{conversation_id}/messages
```

先验证当前 Principal 的会话归属，再按 `(created_at ASC, id ASC)` 返回稳定消息历史。历史接口使用不透明游标分页；响应中的消息保持正序。

### 发送消息

```text
POST /api/v1/chat/completions
Content-Type: application/json
Accept: text/event-stream
```

请求：

```json
{
  "conversation_id": null,
  "content": "你好"
}
```

规则：

- `conversation_id=null` 时自动创建 Conversation，标题使用首条用户消息的规范化截断值。
- 提供 `conversation_id` 时校验当前用户所有权后追加消息。
- 模型使用服务端 `OPENAI_MODEL`，第一版不允许客户端任意指定模型。
- 请求不得由前端或网关自动重发。
- 第一版不提供 `client_request_id`，不按消息文本去重。
- 第一版声明同一会话中的发送由客户端串行执行，不保证并发运行行为。
- 所有 Snowflake `BIGINT` ID 在 JSON 中以字符串传输，避免 JavaScript 安全整数精度问题。

## 发送消息数据流

```text
1. 校验请求和 Principal
2. 创建或校验 Conversation
3. 生成并提交 User Message
4. 创建独立 Graph producer task
5. producer 首先发布 metadata 事件
6. producer 调用 graph.astream_events(...)
7. Adapter 将 LangGraph 消息事件投影为 Chat SSE 事件
8. Graph 正常完成后，从最终 Graph State 取得 AIMessage
9. 提交 Assistant Message
10. 发布 completed 事件
```

Graph 调用只输入本轮新增 HumanMessage：

```python
input = {"messages": [HumanMessage(content=content)]}
config = {"configurable": {"thread_id": str(conversation.id)}}
```

后续轮次的 Graph 历史由 checkpointer 提供，不从业务消息表重复灌入 State。

## SSE 设计

SSE 与 Graph producer 使用同一条逻辑事件序列。`metadata` 由业务层产生，后续内容源自 `astream_events()`，经类似 DeerFlow 的 Adapter 投影后对外暴露稳定协议。

### metadata

每次发送请求的第一帧，不论新会话还是已有会话都发送：

```text
event: metadata
data: {"conversation_id":"201...","user_message_id":"202..."}
```

该事件必须在任何模型 token 之前发布。创建会话与 User Message 的事务必须已提交。

### content_delta

Adapter 只从 LangGraph message 事件中投影用户可见的 assistant 文本增量：

```text
event: content_delta
data: {"content":"你"}
```

LangGraph 的内部 namespace、task、checkpoint、调试元数据和 Python 对象不直接暴露给前端。

### completed

Graph 正常结束且 Assistant Message 已成功写入业务表后发送：

```text
event: completed
data: {"assistant_message_id":"203...","finish_reason":"stop"}
```

`completed` 是成功终止事件。

### error

SSE 建立后的模型或 Graph 异常使用：

```text
event: error
data: {"code":"MODEL_INVOCATION_FAILED","message":"模型调用失败","retryable":true}
```

`error` 是失败终止事件，与 `completed` 互斥。错误前可能已向浏览器发送部分 token，但这些 token 不写入业务表，也不进入失败节点后的 Graph State。

### 连接规则

- SSE 是一条连续连接；`metadata` 与首个 `content_delta` 之间只是等待模型首字的异步间隔。
- 本次不发送定时心跳。单 LLM 节点在 metadata 后很快开始持续输出，当前没有长时间静默的检索、工具或人工审批阶段。
- 响应设置 `Cache-Control: no-cache` 和 `X-Accel-Buffering: no`，避免代理缓冲。
- 本次不实现 event ID、重放缓存或 `Last-Event-ID`。

## 浏览器断连与后台运行

Graph producer 与 `StreamingResponse` consumer 必须解耦：

```text
DetachedChatRunManager
├─ 创建并持有 producer task 强引用
├─ producer 消费完整 astream_events()
├─ SSE consumer 订阅运行事件
└─ producer 完成后清理 task 引用
```

浏览器普通断开时：

- 仅解绑并结束 SSE consumer。
- 不取消 Graph producer。
- producer 继续消费 Graph 事件直至完成或失败。
- 解绑后不再缓存无人消费的 token，避免内存增长。
- 正常完成时即使浏览器已断开，仍写入 Assistant Message；用户刷新会话历史后可以看到最终结果。

本次没有主动停止接口，因此用户侧 AbortSignal、页面关闭和网络断开都不表示业务取消。

## 进程崩溃语义

第一版不扫描或自动恢复未完成 thread。进程在 `llm` 节点执行中崩溃时：

- LangGraph 保留上一个成功 superstep checkpoint。
- 已流出但尚未形成节点返回值的 token 丢失。
- 失败节点的 AIMessage 不进入 Graph State。
- 业务表保留已提交的 User Message，不写 Assistant Message。
- 客户端连接消失，不补发 token。

这与 LangGraph 的 superstep checkpoint 行为一致，不需要逐 token checkpoint、运行恢复器或业务对账器。

## 生命周期与基础设施

Chat API lifespan 启动顺序：

```text
1. 读取现有 Settings
2. 从 DATABASE_URL 解析同一个 PostgreSQL 地址
3. 为 AsyncPostgresSaver 创建独立 psycopg AsyncConnectionPool
4. 创建 AsyncPostgresSaver 并 await setup()
5. 使用 infrastructure.llm 创建 ChatOpenAI
6. 创建 Graph builder
7. compile(checkpointer=checkpointer)
8. 创建 DetachedChatRunManager
9. 将资源保存到 app.state
```

不增加新的 checkpoint 数据库配置。业务 SQLAlchemy 使用现有 asyncpg pool，LangGraph saver 因 SDK 要求使用指向同一 PostgreSQL 的 psycopg pool。通过 SQLAlchemy URL 解析对象转换驱动名，不使用脆弱的字符串替换。

生产 checkpointer 初始化失败时 Chat API 启动失败，不降级到 `MemorySaver`。测试可显式使用 `InMemorySaver`。

关闭时先停止接收新请求，给予后台 run 有限的优雅完成时间，再取消超时任务，最后关闭 psycopg pool。被取消运行保留最近 checkpoint，不执行自动恢复。

## 错误处理

SSE 建立前：

- 空消息或超出长度限制：HTTP 422。
- 会话不存在或不属于当前用户：统一 HTTP 404，避免泄露其他用户会话。
- Conversation 或 User Message 事务失败：HTTP 500，不建立 SSE。
- 模型配置缺失或 checkpointer 初始化失败：Chat API 启动失败。

SSE 建立后：

- 模型或 Graph 异常：发送 `error` 后关闭连接。
- 不保存失败节点的部分 Assistant 内容。
- 不发送 `completed`。
- 日志记录 `conversation_id`、稳定节点名和异常类型，不向客户端暴露供应商凭证、URL 或原始异常详情。

## 测试与验收

### 单元测试

- `ChatState` 使用 LangGraph 消息合并语义。
- Graph 拓扑严格为 `START -> llm -> END`。
- `llm` 节点使用注入模型并返回 AIMessage。
- `llm` 节点没有自动重试策略。
- LangGraph message events 正确投影为 `content_delta`。
- 非用户可见事件被过滤。
- SSE metadata、completed、error 编码正确。
- Conversation/Message Repository 正确执行用户归属、稳定排序和游标分页。

### API 与服务测试

- 第一条消息自动创建 Conversation。
- 首帧始终是 metadata，且早于任何模型 token。
- 已有会话复用 `thread_id=str(conversation.id)`。
- 正常完成后业务表存在 USER/ASSISTANT 消息。
- Graph 失败时业务表只保留 USER 消息，SSE 以 error 结束。
- completed 与 error 互斥。
- 浏览器断连后后台 producer 继续，并最终保存 ASSISTANT 消息。
- 会话列表和消息历史只返回当前用户数据。
- 所有 Snowflake ID 以字符串序列化。

### PostgreSQL 集成测试

- `AsyncPostgresSaver.setup()` 能在现有 PostgreSQL 中初始化内置表。
- 相同 `thread_id` 的第二轮 Graph 能读取第一轮 checkpoint 历史。
- 不同 `thread_id` 的状态相互隔离。
- Chat API 关闭时正确释放 psycopg pool。
- 测试使用假模型，不调用真实 LLM。

### 最终验收

- 聚焦 Chat 测试通过。
- 后端完整测试通过。
- OpenSpec 严格校验通过。
- 全仓不存在重新引入的 `domains/agent`。
- 没有停止、归档、并发控制、自动恢复或 token 级持久化的实现残留。

## 后续演进

未来能力按实际需要增加，不提前创建空壳：

- 主动停止：节点协作式返回累计 AIMessage，使半截回答同时成为有效 Graph State 和业务 Assistant Message，并用 metadata 标记停止原因。
- query rewrite、retrieval、tool 和 answer 节点。
- 条件路由与子图。
- 长时间静默节点出现后增加 SSE 注释心跳。
- 需要弱网自动重试时增加请求幂等键。
- 需要精确流恢复时评估 Agent Server thread streaming 或独立事件日志，不复用 checkpoint 表承载 SSE 重放。
- 需要 Studio/CLI 时增加独立模块级开发 Graph 入口。
