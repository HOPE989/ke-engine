## Context

现有 RAG Graph 已经按无 Checkpointer 的单次请求管线实现：

```text
query_rewrite
  -> query_router
  -> document_hybrid
  -> collect_retrieval_outcomes
```

`document_hybrid` 已复用 Elasticsearch、Embedding、父块缓存和 Qwen3 Rerank，最终在 `RagState.retrieval_outcomes` 中留下可序列化的文档候选。现有 Chat Graph 已完成 BUSINESS、NON_BUSINESS 和 CLARIFY 三态业务理解，但所有 BUSINESS 请求仍进入固定 `business_boundary` 节点。Chat 消息表已经预留 `rag_references` JSONB 字段，现有 repository、消息历史契约和 completion runtime 尚未使用它。

本项目用于面试演示，没有真实用户和生产部署要求。调用发生在本地或可信内网，不需要鉴权、健康检查和生产级弹性治理。实现重点是以最少新增配置跑通：

```text
Chat -> MCP -> RAG Graph -> EvidencePackage -> Grounded Answer
```

## Goals / Non-Goals

**Goals:**

- 用一个内部 Streamable HTTP MCP Tool 暴露现有文档 RAG Graph。
- 用最小 EvidencePackage 隔离 Graph 内部 state 与外部协议。
- 让明确的文档知识类 BUSINESS intent 通过 MCP 获取证据并生成引用回答。
- 将完整回答与引用原子持久化，并在消息历史中返回引用。
- 保持现有 SSE 事件类型和前端消费方式不变。
- 只增加一个 Chat 侧 `rag_mcp_url` 配置和一个本地启动命令。

**Non-Goals:**

- MCP 鉴权、OAuth、Token、租户授权和动态 Tool 可见性。
- SQL、GraphDB、专家 Tool、多个 MCP Endpoint 或通用 Agent Tool 选择。
- 健康检查、readiness、重试、熔断、限流、心跳和连接池优化。
- 跨服务 Trace Context、完整检索诊断和生产部署编排。
- 修改文档入库链路、Hybrid Retrieval 算法或已有索引结构。
- 新增前端引用组件；首版引用通过回答文本与消息历史数据体现。

## Decisions

### 1. 一个 change 内按四个子阶段交付

本次工作作为一个 `complete-document-rag-mcp-integration` change 管理。`tasks.md` 按“RAG 输出收口、MCP 暴露、Chat 接入、端到端验证”四个子阶段组织，不创建多个独立 change。

这样既保留清晰 checkpoint，也避免扫尾工作被人为拆成多个 proposal 和 archive 周期。

### 2. MCP 只暴露 `retrieve_evidence`

首版只提供：

```text
/mcp
└── retrieve_evidence
```

Tool 接收当前查询、可选对话上下文、可选业务 intent 和文档范围，返回结构化 EvidencePackage。它不返回最终业务答案。

不暴露 `search_documents` 原子 Tool，也不注册 SQL/Graph 空 Tool。Chat 是固定 Workflow，通过代码中的 MCP Client 调用 Tool，不把 Tool Discovery 和调用决策交给模型。

### 3. MCP SDK 只存在于服务和客户端适配层

RAG 侧分层：

```text
entrypoints/rag_mcp.py
  -> services/rag_mcp
  -> domains/rag/services/retrieve_evidence.py
  -> RAG Graph
```

Chat 侧通过一个窄 `RagClient` 协议依赖 RAG，生产适配器使用官方 MCP Python SDK，测试使用 fake。`domains/rag` 和 Chat Graph 节点都不导入 MCP SDK 类型。

### 4. EvidencePackage 使用文档专用最小契约

首版协议不提前抽象异构证据：

```text
EvidencePackage
├── query
├── standaloneQuery
└── evidenceItems[]
    ├── citationId
    ├── content
    ├── docId
    ├── chunkId
    ├── fileName?
    ├── url?
    └── rerankScore?
```

`citationId` 使用稳定的 `<docId>:<chunkId>`。`SUCCESS` outcome 投影为一个或多个 evidence item；`EMPTY` outcome 返回空数组；`FAILED` outcome 抛出应用异常并使 MCP Tool 调用失败。首版不返回 trace ID、完整 retrieval plan、applied filters 或内部阶段诊断。

### 5. 文档范围由可信 Chat 调用方直接传递

本次没有鉴权。Tool 请求仍携带现有 Retriever 必需的 `accessibleBy`，RAG 只执行 Pydantic 形状校验并绑定为请求级 immutable scope，不验证调用方身份或重新计算权限。

Chat 使用当前 `principal.user_id` 作为唯一 `accessibleBy` 值。面试演示上传文档时使用相同值。`docIds` 保留为可选缩小条件。

这是一项明确的可信内网假设，不代表生产授权设计。

### 6. RAG MCP 复用现有运行资源和配置

RAG MCP lifespan 复用 Studio 已验证的装配组件创建：

- Chat Model
- Embedding Model
- Elasticsearch client/store
- Qwen3 Reranker
- Parent chunk cache 及其现有 PostgreSQL/Redis 依赖
- Langfuse callback（配置存在时）

服务固定用于本地启动，不增加健康检查。Chat 只新增 `rag_mcp_url`；MCP 服务监听地址和端口通过本地启动入口的固定默认值提供，不增加另一组配置。

### 7. Chat 通过 intent 确定性进入文档 RAG

以下 intent 进入 `knowledge_rag`：

- `POLICY_RULE_QA`
- `TRANSPORT_OPERATION_QA`
- `COAL_SALES_QA`
- `PROFESSIONAL_KNOWLEDGE_QA`

`BUSINESS_DATA_QUERY` 和 `OTHER_BUSINESS` 继续进入确定性的未接入边界。NON_BUSINESS 和 CLARIFY 行为保持不变。

目标拓扑：

```text
business_understanding
├── NON_BUSINESS -> llm -> END
├── CLARIFY -> interrupt -> resume
├── unsupported BUSINESS -> business_boundary -> END
└── document knowledge BUSINESS
      -> knowledge_rag
      -> grounded_answer
      -> END
```

`knowledge_rag` 从消息 state 取得当前问题，并传递此前最近十条 USER/ASSISTANT 消息作为对话上下文；这是固定应用策略，不新增 Token Budget 配置。

### 8. MCP Client 通过 Chat runtime context 注入

`ChatRuntimeContext` 增加 `rag_client` 和当前 `user_id`。客户端对象不进入 checkpoint state。`knowledge_rag` 只调用协议方法并把可序列化 EvidencePackage 和引用列表写入 Chat state。

Studio 继续复用同一个 Graph builder，但允许注入 fake 或显式绑定的开发 RagClient，不在 Studio 中启动 RAG MCP 服务。

### 9. Grounded Answer 复用 Chat 模型并保持 SSE 契约

`grounded_answer` 使用运行时注入的 Chat model，根据当前问题和 evidence items 构造受约束 Prompt。Prompt 要求回答只使用给定证据，并以 `[1]`、`[2]` 等编号引用对应 evidence item。

当 EvidencePackage 为空时，节点直接返回确定性文本“未检索到相关依据。”，不调用模型。

Completion runtime 将 `llm` 和 `grounded_answer` 两个节点的模型文本投影为现有 `content_delta`，不新增 SSE 事件类型。

### 10. 成功 Graph 运行后读取引用并原子持久化

`knowledge_rag` 将最小引用列表写入 checkpointed Chat state。Graph 正常到达 END 后，CompletionProducer 从同一 thread 的最终 state 读取本轮 `rag_references`，并和完整 ASSISTANT 文本一起交给 `MessageRepository.add_assistant`。

ASSISTANT 内容与引用在同一个数据库事务中提交；提交成功后才发送 `completed`。非 RAG、澄清和空证据回答保存空引用数组。消息历史响应增加 `rag_references`。

### 11. 验证聚焦一个真实闭环

默认测试使用 fake MCP client 验证 Graph 路由、证据回答、SSE 投影和引用持久化。另增加一个显式集成测试或可重复脚本，通过真实 Streamable HTTP 调用已启动的 RAG MCP，证明 Tool 能返回现有 Elasticsearch 文档证据。

不建立生产级失败矩阵、性能基线和发布门禁。

## Risks / Trade-offs

- [无鉴权的 MCP Endpoint 可被能访问端口的进程调用] → 接受可信本地/内网假设，不对外暴露端口。
- [`accessibleBy=user_id` 要求演示数据使用相同值] → 在演示和测试数据准备步骤中固定该约定。
- [固定最近十条上下文可能超出某些模型预算] → 面试样例保持短会话，不在本次增加 Token 预算器。
- [MCP 或 RAG 失败会让 completion 失败] → 接受最小实现，沿用现有 `error` SSE 终态，不增加降级回答。
- [同一 Change 横跨两个服务和持久化] → tasks 按四个子阶段提供可独立验证的 checkpoint。
- [MCP SDK major 版本变化] → 在依赖中固定实现所使用的 major 版本，不使用无上界依赖。
