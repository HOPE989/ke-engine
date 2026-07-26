## Why

Query Router 已能产出 `DOCUMENT_HYBRID` 计划，但 RAG Graph 尚未执行任何真实检索。实现首个文档混合检索器，可以把现有 Elasticsearch 向量数据转化为可用检索结果，并建立后续 SQL、Graph Retriever 共用的动态执行与结果汇合基础。

## What Changes

- 参考 know-engine 的检索职责分层，自定义标准 LangChain `BaseRetriever`：复用现有 `ElasticsearchStore` 执行 KNN，使用同一 Elasticsearch client 执行 BM25，并在应用层并行调用和执行固定参数 RRF。
- 在 BM25 与 KNN 子查询中强制应用同一组服务端知识库范围和访问范围过滤，Router 选择不能绕过授权。
- 定义可序列化的 Document Candidate、`RetrievalOutcome` 和 Graph state reducer，并明确完整 Hybrid 请求的成功、空结果和失败语义。
- 将 Query Router 从静态 `query_router -> END` 改为只跳转到实际注册的 Retriever；当前生产 Graph 仅注册 `document_hybrid`。
- 新增 `collect_retrieval_outcomes` 汇合节点，当前拓扑结束于已汇合的文档检索结果。
- 补强 Elasticsearch 索引 mapping，使同一索引同时支持全文检索、向量检索及元数据精确过滤。
- 新增离线 fake 测试和显式 Elasticsearch 集成测试，验证应用层 RRF、共享过滤条件以及开源版 Elasticsearch 的真实 BM25/KNN 检索。
- 本 change 不实现 Document Rerank、EvidencePackage、SQL/Graph Retriever、跨 Retriever fallback、MCP 或 Chat API 集成。

## Capabilities

### New Capabilities

- `rag-hybrid-document-retrieval`: 定义文档混合检索输入、Elasticsearch BM25/KNN 子检索、应用层 RRF、授权过滤、结果协议、Graph 汇合和测试要求。

### Modified Capabilities

- `rag-query-router`: 将 Router 计划连接到实际注册的 Retriever 节点，并从已注册节点生成可路由能力集合。
- `document-vector-storage`: 补充 Elasticsearch 索引对全文检索和元数据精确过滤所需的 mapping 要求。

## Impact

- 影响 `backend/app/domains/rag/`，新增文档检索契约、Graph 节点、outcome reducer 和汇合节点。
- 影响 `backend/app/infrastructure/elasticsearch.py`，增加自定义 Hybrid Retriever、全文/向量子检索、应用层 RRF、请求级 filter 及可检索 mapping 校验。
- 影响 RAG Graph Builder、Studio 装配、Router node 返回类型和现有 RAG 测试。
- 复用现有 LangChain `BaseRetriever`、`ElasticsearchStore`、Embedding Model、LangGraph 和 Langfuse callback，不新增外部服务或对外 API，不依赖 Elasticsearch 企业版 RRF。
