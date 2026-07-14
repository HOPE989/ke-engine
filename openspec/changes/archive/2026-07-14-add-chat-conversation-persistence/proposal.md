## Why

正式 Chat 链路需要一套独立于 LangGraph checkpoint 的业务权威数据，用于持久化用户会话和最终可见消息。当前 `chat` 领域尚无持久化模型，因此先建立最小的会话数据基础，后续 Chat API、SSE 与运行时一致性设计才能在稳定边界上演进。

## What Changes

- 新增 `conversations` 业务表，保存会话 ID、用户归属、标题、状态和创建/更新时间。
- 新增 `messages` 业务表，保存会话内的用户及助手消息、父消息关系、问题改写结果、模型统计预留字段、RAG 引用、扩展元数据和时间信息。
- 使用应用生成的 Snowflake `BIGINT` 作为两张表的主键，并通过外键表达消息所属会话和消息分支关系。
- 为会话列表、会话消息排序和父消息查询建立必要的约束与索引。
- 新增 SQLAlchemy ORM 映射、Alembic 迁移以及覆盖模型和迁移契约的自动化测试。
- 保持 `rag_references` 为默认空数组的 JSONB 字段；本次不固定其中元素的数据结构。
- 本次不增加 Chat API、SSE 流式协议、LangGraph/PostgresSaver 初始化、业务表与 checkpoint 的写入一致性、异步标题生成或 RAG MCP 调用。

## Capabilities

### New Capabilities

- `chat-conversation-persistence`: 定义 Chat 会话和消息的最小权威持久化模型、数据库约束及索引。

### Modified Capabilities

- None.

## Impact

- Backend domain: `backend/app/domains/chat/` 将新增会话持久化模型。
- Database: 新增 `conversations` 和 `messages` 两张 PostgreSQL 表及对应 Alembic migration。
- Alembic: migration metadata 需要加载 Chat ORM 模型。
- Tests: 新增 Chat ORM 与 migration schema 契约测试。
- APIs and external systems: 无新增 API，也不引入新的外部依赖或运行时服务。
