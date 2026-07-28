## Why

文档 RAG 已经完成 Query Rewrite、路由、Hybrid Retrieval、父块扩展、RRF 和 Rerank，但当前结果仍停留在内部 `retrieval_outcomes`，Chat 的业务分支也仍以固定边界消息结束。需要用一次扫尾变更把现有 RAG Graph 暴露为内部 MCP 服务，并让 Chat 基于返回证据生成和持久化可引用回答，形成可用于面试演示的完整文档 RAG 闭环。

## What Changes

- 新增一个无会话的内部 RAG MCP 服务，通过 Streamable HTTP 暴露 `retrieve_evidence` Tool。
- 新增最小 `EvidencePackage`，把现有文档候选投影为内容、文档来源和 Rerank 分数；空检索返回空证据包，执行失败作为 MCP 调用失败。
- Chat 的所有 `BUSINESS` 请求都通过 MCP 调用 RAG；Intent 只选择回答 Prompt，不再决定检索数据源或是否进入 RAG。
- 将依赖会话历史的 Query Rewrite 移到 Chat，作为 `contextualize_query` 产出 standalone query；RAG MCP 保持无会话。
- Chat 基于 MCP 返回证据和 Intent 对应 Prompt 生成带引用回答。
- Chat SSE 和前端实验室展示本轮稳定节点链路、RAG 选择的 Retriever、Standalone Query 与召回正文。
- 完整回答与引用在同一个 ASSISTANT 消息事务中持久化，并通过消息历史接口返回。
- 只新增 Chat 侧不可避免的 `rag_mcp_url`；RAG 服务复用现有模型、Elasticsearch、Embedding、Rerank、Redis、PostgreSQL 和 Langfuse 配置。
- 本次不增加鉴权、健康检查、重试、熔断、限流、跨服务 Trace Context、专家 Endpoint、SQL Retriever 或 GraphDB Retriever。

## Capabilities

### New Capabilities

- `rag-mcp-service`: 定义内部 `retrieve_evidence` MCP Tool、最小请求/响应契约、现有文档 RAG Graph 的应用服务封装和本地启动方式。

### Modified Capabilities

- `chat-langgraph-runtime`: 所有 BUSINESS 路径统一执行 `contextualize_query -> business_rag -> grounded_answer`，通过 Intent 选择回答 Prompt，并通过运行时上下文注入 MCP Client。
- `chat-streaming-completion`: 将 grounded answer 的模型输出投影为现有 `content_delta`，增加最小调试事件，并在成功持久化回答和引用后发送 `completed`。
- `chat-conversation-persistence`: 为非空文档 RAG 结果定义最小引用元素并与 ASSISTANT 消息原子持久化。
- `chat-conversation-api`: 在消息历史中返回已持久化的 RAG 引用。

## Impact

- 新增官方 MCP Python SDK 依赖、RAG MCP entrypoint、服务适配层和 Chat MCP Client 适配器。
- 修改 Chat Graph state、runtime context、业务路由、查询上下文化、Intent Prompt、completion 事件投影、ASSISTANT 持久化、消息历史契约和前端实验室。
- 增加一个本地 RAG MCP 启动命令和一个 Chat 侧 MCP URL 配置。
- 复用现有 RAG Graph 和检索基础设施；不修改文档入库链路、Hybrid Retrieval 算法、数据库 schema、前端协议或生产部署体系。
