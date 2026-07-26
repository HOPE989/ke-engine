## Context

当前 RAG Graph 能完成 Query Rewrite 和 Query Router，但 Router 只写入计划并静态结束。文档 segment 已写入 Elasticsearch，正文位于 `text`，向量位于 `vector`，来源与访问范围位于 `metadata`。

项目使用开源版 Elasticsearch。项目锁定的 `langchain-elasticsearch` 在 `DenseVectorStrategy(hybrid=True)` 下默认使用 Elasticsearch 原生 RRF Retriever，但该能力需要非 Basic 许可证，真实集成测试会返回 403。因此本 change 参考 know-engine 的职责分层，自定义标准 LangChain `BaseRetriever`，复用 Elasticsearch 的 BM25、KNN 和 LangChain Embedding 能力，仅在应用层实现并发编排与 RRF。

## Goals / Non-Goals

**Goals:**

- 使用自定义 LangChain `BaseRetriever` 封装现有 Elasticsearch BM25 与 `ElasticsearchStore` KNN。
- 对 BM25 与 KNN 使用完全相同、服务端提供的访问范围和文档范围过滤。
- 在应用层使用固定 RRF 参数融合、去重并截断结果。
- 以稳定 `RetrievalOutcome` 写入 Graph state，并为后续多个 Retriever 并行写入提供 reducer。
- 让 Query Router 只跳转到真实注册的 `document_hybrid` 节点。
- 通过离线 fake 测试与显式 Elasticsearch 集成测试证明纵向链路。

**Non-Goals:**

- 不自行实现 BM25、KNN 或 Embedding 算法。
- 不要求对外返回各子检索的原始 score、rank 或独立诊断。
- 不实现单子检索降级；两个子检索作为一个 Hybrid 操作整体成功或失败。
- 不实现 Document Rerank、多查询扩展、EvidencePackage 或回答。
- 不实现 SQL、Graph Retriever 或其占位节点。
- 不接入 Chat API、MCP、checkpoint 或跨 Retriever fallback。
- 不在本 change 引入 IK、拼音或领域词典 analyzer。

## Decisions

### 1. 请求级 Retriever 绑定服务端授权范围

`document_hybrid` 从 `RagState` 读取 `standalone_query` 和服务端调用方提供的 `document_retrieval_scope`。scope 至少包含一个非空 `accessibleBy` 值，并可选限制 `docId` 集合。

共享的 `ElasticsearchStore` 持有索引信息和 Embedding Model，共享 Elasticsearch client 用于全文检索。Retriever factory 针对每次 Graph 请求创建一个自定义 `ElasticsearchHybridRetriever`，只保存已验证的不可变 scope 与检索预算。每次子检索都从该 scope 重新生成相同 filter；不得修改进程级共享 Retriever 的 filter，也不得从 Retriever 内读取全局用户或 Chat 会话。

scope 缺失、为空或非法时，在创建 Retriever 和访问 Elasticsearch 前 fail closed。Router 只决定是否执行 Retriever，不授予文档权限。

### 2. 自定义标准 Retriever 编排两个基础检索

向量子检索使用非 Hybrid 的 `ElasticsearchStore`：

```python
DenseVectorStrategy(
    hybrid=False,
)
```

自定义 `ElasticsearchHybridRetriever(BaseRetriever)` 的异步路径并行执行：

```text
ElasticsearchHybridRetriever.ainvoke(query)
├── full_text_search: bool.must(match(text)) + shared filters
├── vector_search: ElasticsearchStore.asimilarity_search + shared filters
└── reciprocal_rank_fusion(k=60) → deduplicate → result_limit
```

BM25 使用 Elasticsearch 默认 similarity；KNN 和 Embedding 继续由 LangChain `ElasticsearchStore` 提供。应用层只实现两个调用的并发、按稳定 `chunkId` 去重的 RRF 和结果截断，不归一化或混合原始 score。同步 `invoke` 保持标准 Retriever 兼容性；生产 Graph 使用 `ainvoke` 的并发路径。

### 3. 精确过滤字段由 mapping 保证

同一索引继续承载写入与检索：

- `text`：BM25 全文检索；
- `vector`：KNN Dense 检索；
- `metadata.docId`、`metadata.chunkId`、`metadata.accessibleBy`：`term` / `terms` 精确过滤和来源定位。

新索引创建时显式声明这些字段。现有索引 mapping 不兼容时启动或装配明确失败，不允许退化为无过滤检索；部署时需要重建或 reindex 现有开发索引。

中文分词本轮沿用目标 Elasticsearch 的现有 analyzer。引入额外 analyzer 或插件会改变索引迁移和部署要求，留给独立 change。

### 4. Graph node 转换标准 Document

LangChain Retriever 返回标准 `list[Document]`。`document_hybrid` Graph node 只负责：

1. 校验 query 和 scope；
2. 创建请求级 `ElasticsearchHybridRetriever`；
3. 调用 `ainvoke` 并传播 Runnable config；
4. 把 `Document.page_content` 与 metadata 转换为领域 Candidate；
5. 写入一个 `RetrievalOutcome`。

Hybrid 返回文档时 outcome 为 `SUCCESS`，空列表为 `EMPTY`，普通 Elasticsearch/Embedding 依赖失败转换为 `FAILED`。运行时取消和非普通异常继续传播。state 不保存 store、retriever、client、model、callback 或异常对象。

Candidate 本轮不承诺暴露融合 score 或子检索 rank；这些值只用于 Retriever 内部排序。后续若 EvidencePackage 确实需要 score，再单独扩展领域契约。

### 5. 检索参数在装配时注入

最终结果数 `result_limit`、每路候选数 `candidate_limit`、固定 `rank_constant=60` 和请求 timeout 由不可变 `DocumentRetrievalOptions` 在入口装配。`candidate_limit` 必须不小于最终结果数；domain import 不读取 Settings。

### 6. 使用类型化 outcome 和按 Retriever ID 合并的 reducer

`document_hybrid` 输出：

```text
RetrievalOutcome
├── retriever_id = DOCUMENT_HYBRID
├── status = SUCCESS | EMPTY | FAILED
├── candidates
└── diagnostics
    ├── duration_ms
    └── result_count
```

`RagState.retrieval_outcomes` 使用确定性 reducer 按 `retriever_id` 合并，并拒绝同一 superstep 中同一 Retriever 的重复写入。

### 7. Router 使用 Command 跳转到注册节点

目标拓扑为：

```text
START
  → query_rewrite
  → query_router
      └─ Command(goto="document_hybrid")
  → document_hybrid
  → collect_retrieval_outcomes
  → END
```

Builder 从实际注册的 Retriever 节点生成 Router 能力集合。当前只注册 `DOCUMENT_HYBRID`，不得注册 SQL/Graph 空节点。`collect_retrieval_outcomes` 验证计划中的每个 Retriever 都产生了 outcome。

## Risks / Trade-offs

- [两路检索延迟或失败不一致] → 异步路径并发执行，并保持全有或全无语义；任一路普通失败都由 Graph node 转为一个脱敏 `FAILED` outcome。
- [RRF 中重复或并列结果不稳定] → 以非空 `chunkId` 作为身份键，固定 `k=60`，并使用确定性 tie-break。
- [现有 mapping 不兼容精确过滤] → fail closed，并在部署时重建或 reindex 索引。
- [LangChain Hybrid 模式不返回 score] → 本轮只返回排序后的 Document，不伪造或反推 score。
- [默认 analyzer 的中文召回不足] → 先验证真实语料；需要时单独设计 analyzer change。
- [当前 Router 只看到一个能力] → 后续 SQL/Graph change 从注册节点扩展能力集合。
- [当前 collect 后没有最终回答] → EvidencePackage 和回答属于后续 change。

## Migration Plan

1. 部署前检查目标 Elasticsearch 版本和索引 mapping；不要求企业版 RRF 许可证。
2. mapping 不兼容时重建或 reindex 文档向量索引，并重新执行已有文档的向量存储。
3. 在开源版 Elasticsearch 上运行显式集成测试，验证 BM25、KNN、应用层 RRF、ACL/docId filters、空结果和失败行为。
4. 集成测试通过后启用新的 RAG Studio Graph。
5. 回滚时恢复旧 Graph Builder；保留新增 mapping 不影响旧向量写入。

## Open Questions

无。Analyzer、Document Rerank、EvidencePackage 和跨 Retriever fallback 在后续 change 中决策。
