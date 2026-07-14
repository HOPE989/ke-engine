## Context

`backend/app/domains/chat/` 目前为空，正式 Chat 链路还没有业务持久化模型。后续系统会使用 LangGraph `PostgresSaver` 保存运行时 checkpoint，但 checkpoint 不承担对话列表、历史消息和用户可见结果的业务权威职责。本次只建立最小业务数据基础，不实现任何运行链路。

现有后端使用 PostgreSQL、SQLAlchemy 2.x async ORM、Alembic 和应用侧 Snowflake 64 位 ID。Chat 模型应沿用这些约定，并与 `document` 领域对 JSONB `metadata` 的映射方式保持一致。

## Goals / Non-Goals

**Goals:**

- 建立只包含 `conversations` 与 `messages` 的最小 Chat 持久化模型。
- 通过数据库约束保证状态、角色、会话归属和父消息关系的基本完整性。
- 支持线性消息历史，并为基于 `parent_message_id` 的回答分支保留数据能力。
- 为会话列表、消息顺序和分支子节点查询提供稳定索引。
- 提供可升级、可回滚且有自动化契约测试覆盖的 Alembic migration。

**Non-Goals:**

- 不实现 Conversation/Message repository、Chat API、SSE 或前端契约。
- 不初始化或管理 LangGraph/PostgresSaver 表。
- 不设计业务表与 LangGraph checkpoint 的写入时序、补偿或恢复策略。
- 不实现标题生成、消息编辑、重新生成、分支切换或删除接口。
- 不增加项目、文件夹、分享、Artifact、用量统计或 API Key 等外围表。
- 不固定 `rag_references` 数组元素结构，也不实现 RAG MCP 协议。

## Decisions

### 1. 业务持久化只使用两张表

`conversations` 表示用户可见的一次业务会话，`messages` 表示该会话中的用户和助手消息。它们是后续 Chat 产品数据的权威来源；LangGraph checkpoint 是独立的运行时数据。

本次不引入 `agent_runs`、`turns` 或映射表。系统只有一个主图入口，后续可直接把 `str(conversations.id)` 用作 LangGraph `thread_id`，但代码和数据库都不在本次创建 `thread_id` 字段。

### 2. 主键沿用应用侧 Snowflake BIGINT

两张表的 `id` 均为无数据库 identity/default 的 `BIGINT` 主键，由现有 `SnowflakeIdGenerator` 在应用侧生成。`conversations.id` 同时就是业务 conversation identity，不额外增加 `conversation_id`。

未来 API 必须把 64 位 ID 序列化为字符串以规避 JavaScript 安全整数限制，但 API 契约不属于本次实现。

### 3. Conversation 保持最小字段集合

`conversations` 包含：

- `id BIGINT PRIMARY KEY`
- `user_id VARCHAR(255) NOT NULL`
- `title VARCHAR(255) NOT NULL`
- `status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP`

`status` 只允许 `ACTIVE`、`ARCHIVED`、`DELETED`。不增加 `tenant_id`、`project_id`、`thread_id`、模型设置或统计字段。首条用户消息截断生成临时标题及后续异步标题更新均由后续应用层负责。

### 4. Message 保存用户可见内容和必要扩展点

`messages` 包含：

- `id BIGINT PRIMARY KEY`
- `conversation_id BIGINT NOT NULL`
- `parent_message_id BIGINT NULL`
- `role VARCHAR(32) NOT NULL`
- `content TEXT NOT NULL`
- `transformed_content TEXT NULL`
- `token_count INTEGER NULL`
- `model_name VARCHAR(255) NULL`
- `rag_references JSONB NOT NULL DEFAULT '[]'::jsonb`
- `metadata JSONB NOT NULL DEFAULT '{}'::jsonb`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP`

`role` 只允许 `USER`、`ASSISTANT`，不持久化 Graph 内部的 system/tool/MCP 中间消息。`messages` 不设置状态字段：正常完成或用户主动停止后保留的半截回答都是有效 assistant message；停止原因可由后续运行链路写入 `metadata`。

`transformed_content` 保存用户问题改写结果。`token_count` 与 `model_name` 先保留为 nullable 字段，本次不定义由哪个 Graph 节点赋值。

### 5. 父消息关系必须留在同一会话

除 `conversation_id -> conversations.id` 外，使用 `(conversation_id, parent_message_id) -> messages(conversation_id, id)` 的复合自引用外键，防止消息引用另一个会话的父消息。为满足 PostgreSQL 被引用列唯一性要求，增加 `UNIQUE (conversation_id, id)`。

根消息的 `parent_message_id` 为 `NULL`。数据库不强制 USER/ASSISTANT 角色交替，也不在本次实现“当前激活分支”概念。硬删除 conversation 时通过 `conversation_id` 外键级联删除其 messages；单独删除父消息不提供级联语义。

### 6. JSONB 字段只固定容器类型

`rag_references` 固定为 JSON array 默认值，具体引用元素等 RAG MCP 输出协议确定后再定义。`metadata` 固定为 JSON object 默认值，用于承载少量非核心、可演进信息。数据库本次不增加 JSON Schema 约束。

由于 SQLAlchemy Declarative 已占用 `metadata` 名称，ORM 属性使用 `metadata_ = mapped_column("metadata", JSONB, ...)`，数据库列名仍保持 `metadata`。

### 7. 索引同时服务过滤和稳定排序

- `conversations (user_id, status, updated_at DESC, id DESC)`：支持按用户和状态列出最近更新会话。
- `messages (conversation_id, created_at ASC, id ASC)`：支持稳定加载会话消息；`id` 处理相同时间戳。
- `messages (conversation_id, parent_message_id)`：支持查找同一父消息的回答分支，并配合父消息完整性约束。

不把 Snowflake ID 单独当作消息业务顺序；读取顺序明确使用 `(created_at, id)`。

## Risks / Trade-offs

- [Risk] `rag_references` 暂无元素级约束，后续生产者可能写出不一致结构 → 本次仅提供存储容器，RAG MCP 协议确定时在应用边界增加类型校验和版本策略。
- [Risk] 业务表与 LangGraph checkpoint 可能在后续运行链路中发生双写不一致 → 本次不执行双写；在 Chat runtime 变更中单独设计写入时序和失败恢复。
- [Risk] 复合自引用外键和附加唯一约束增加少量写入与存储成本 → 接受该成本，以数据库级保证父消息不会跨会话。
- [Risk] Snowflake BIGINT 超过 JavaScript 安全整数范围 → 后续 HTTP/SSE 契约统一以字符串传递 ID。
- [Risk] `updated_at` 的 ORM `onupdate` 不会因插入 message 自动更新 conversation → 后续 repository 必须在写消息事务中显式更新 conversation；本次仅定义列和默认值。

## Migration Plan

1. 在当前 Alembic head `202607080001` 之后新增 migration。
2. upgrade 先创建 `conversations`，再创建 `messages`、约束和索引。
3. 在 Alembic `env.py` 中导入 Chat models，使 autogenerate metadata 可见。
4. downgrade 先删除 `messages`，再删除 `conversations`。
5. 当前开发阶段允许清空数据库，不迁移或回填旧 Chat 数据。

## Open Questions

- `rag_references` 元素结构将在 RAG MCP 检索返回协议确定后处理，不阻塞本变更。
- `token_count`、`model_name` 的代表节点和赋值语义将在 Chat Graph 设计阶段处理，不阻塞本变更。
