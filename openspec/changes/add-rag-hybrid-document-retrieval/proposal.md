## Why

Query Router 已能产出 `DOCUMENT_HYBRID` 计划，但 RAG Graph 尚未执行任何真实检索。实现首个文档混合检索器，可以把现有 Elasticsearch 向量数据转化为可用检索结果，并建立后续 SQL、Graph Retriever 共用的动态执行与结果汇合基础。

## What Changes

- 使用现有 `ElasticsearchStore` 的 `DenseVectorStrategy(hybrid=True)` 和 `as_retriever()` 实现 `DOCUMENT_HYBRID`，由 Elasticsearch 在一次请求中执行 BM25、KNN 和原生 RRF。
- 在 BM25 与 KNN 子查询中强制应用同一组服务端知识库范围和访问范围过滤，Router 选择不能绕过授权。
- 定义可序列化的 Document Candidate、`RetrievalOutcome` 和 Graph state reducer，并明确完整 Hybrid 请求的成功、空结果和失败语义。
- 将 Query Router 从静态 `query_router -> END` 改为只跳转到实际注册的 Retriever；当前生产 Graph 仅注册 `document_hybrid`。
- 新增 `collect_retrieval_outcomes` 汇合节点，当前拓扑结束于已汇合的文档检索结果。
- 补强 Elasticsearch 索引 mapping，使同一索引同时支持全文检索、向量检索及元数据精确过滤。
- 新增离线 fake 测试和显式 Elasticsearch 集成测试，验证 LangChain 生成的 Hybrid DSL、过滤条件和目标 Elasticsearch 对原生 RRF 的兼容性。
- 本 change 不实现 Document Rerank、EvidencePackage、SQL/Graph Retriever、跨 Retriever fallback、MCP 或 Chat API 集成。

## Capabilities

### New Capabilities

- `rag-hybrid-document-retrieval`: 定义文档混合检索输入、Elasticsearch 原生 BM25/KNN Hybrid 与 RRF、授权过滤、结果协议、Graph 汇合和测试要求。

### Modified Capabilities

- `rag-query-router`: 将 Router 计划连接到实际注册的 Retriever 节点，并从已注册节点生成可路由能力集合。
- `document-vector-storage`: 补充 Elasticsearch 索引对全文检索和元数据精确过滤所需的 mapping 要求。

## Impact

- 影响 `backend/app/domains/rag/`，新增文档检索契约、Graph 节点、outcome reducer 和汇合节点。
- 影响 `backend/app/infrastructure/elasticsearch.py`，增加原生 Hybrid `ElasticsearchStore` 装配、请求级 filter 及可检索 mapping 校验。
- 影响 RAG Graph Builder、Studio 装配、Router node 返回类型和现有 RAG 测试。
- 复用现有 LangChain `VectorStoreRetriever`、`ElasticsearchStore`、Embedding Model、LangGraph 和 Langfuse callback，不新增外部服务或对外 API。
