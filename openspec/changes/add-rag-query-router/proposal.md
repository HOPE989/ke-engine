## Why

Query Rewrite 已能生成独立检索查询，但 RAG Graph 尚不能判断问题需要文档、结构化数据还是图关系证据。新增 Query Router 可以先形成稳定、可评测的检索计划，为后续 Retriever 节点的动态并行执行建立入口。

## What Changes

- 在 Query Rewrite 后新增 `query_router` 节点，根据 `standalone_query` 从 `DOCUMENT_HYBRID`、`SQL`、`GRAPH` 中选择一个或多个 Retriever。
- 使用受严格校验的结构化模型输出，并将其规范化为可序列化的 `RetrievalPlan`。
- Router 只选择装配时显式提供的可路由能力；服务端再次校验模型结果，不把模型路由视为授权。
- Router 普通异常、超时或非法输出时不重试；`DOCUMENT_HYBRID` 可用时回退到该能力，否则明确失败，不执行全量检索。
- 将 RAG Graph 增量拓扑扩展为 `START -> query_rewrite -> query_router -> END`，本 change 只产出计划，不执行 Retriever。
- 新增离线契约测试和显式真实模型评测入口，覆盖单选、多选、能力约束和 fallback。
- 本 change 不实现 Document、SQL 或 Graph Retriever，不实现动态并行、结果汇合、Rerank、EvidencePackage 或跨 Retriever 执行降级。

## Capabilities

### New Capabilities

- `rag-query-router`: 定义检索器路由的输入输出、多选规则、能力边界、失败回退、RAG Graph 集成及评测要求。

### Modified Capabilities

- `rag-query-rewrite`: 将当前 RAG Graph 增量拓扑的终点从 Query Rewrite 调整为 Query Router，同时保持 Rewrite 自身行为不变。

## Impact

- 影响 `backend/app/domains/rag/graph/` 中的 state、builder、节点导出和新增 Router 模块。
- 影响现有 RAG Graph、Studio 入口和 Query Rewrite 评测对最终 Graph 输出及拓扑的断言。
- 复用现有 LangChain、LangGraph、模型注入和 Langfuse callback 机制，不新增外部依赖或对外 API。
- 为后续注册真实 Retriever 并使用 LangGraph 动态并行执行预留稳定的 `RetrievalPlan` 契约。
