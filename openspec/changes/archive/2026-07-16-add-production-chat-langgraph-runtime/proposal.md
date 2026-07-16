## Why

Chat 领域目前只有会话与消息的持久化结构，尚不能创建会话、查询历史或通过 LangGraph 流式生成回答。现在需要建立一条可直接演进到 RAG Chat 的生产级最小链路，同时保持业务数据与 LangGraph checkpoint 各自职责清晰。

## What Changes

- 增加当前用户的会话列表与消息历史查询能力，并在发送首条消息时由后端自动创建会话。
- 增加基于 SSE 的 Chat completion 接口：首个事件返回会话与用户消息标识，后续事件投影 LangGraph 流式输出，并以互斥的成功或失败事件结束。
- 增加最小 Chat Graph，拓扑固定为 `START -> llm -> END`，但按生产级方式注入模型、持久化 checkpoint、管理资源生命周期。
- 复用现有 PostgreSQL：业务会话和消息仍是用户可见历史的权威来源，LangGraph 自带 checkpoint 表仅服务运行时恢复。
- 普通浏览器断开不取消后台 Graph；节点异常或进程崩溃时丢弃未完成节点的部分回答，并保持业务消息与最后成功 checkpoint 一致。
- 首版不实现用户主动停止、会话归档、请求幂等、并发发送、token 重放、自动恢复扫描或节点自动重试。

## Capabilities

### New Capabilities

- `chat-conversation-api`: 当前用户的会话列表、消息历史以及首条消息自动创建会话的 HTTP 契约。
- `chat-streaming-completion`: Chat completion 的 SSE 事件协议、持久化时序、断连与失败语义。
- `chat-langgraph-runtime`: 单节点 Chat Graph、模型注入、PostgreSQL checkpointer 与应用生命周期契约。

### Modified Capabilities

无。现有 `chat-conversation-persistence` 的数据库结构与约束保持不变，本变更只消费该能力。

## Impact

- 新增 Chat API contracts、repositories、services、FastAPI router/entrypoint 与 SSE 适配层。
- 新增 Chat Graph state、builder、LLM node，以及 LangGraph PostgreSQL checkpointer 基础设施。
- 扩展应用依赖与配置以支持 LangGraph、psycopg 连接池和服务端固定模型。
- 增加单元、API 与 PostgreSQL 集成测试；现有数据库业务表不新增迁移。
