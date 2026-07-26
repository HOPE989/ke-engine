## Context

当前 RAG Graph 能完成 Query Rewrite 和 Query Router，但 Router 只写入计划并静态结束。文档 segment 已由现有异步流程写入 Elasticsearch，其中正文位于 `text`，向量位于 `vector`，来源与访问范围位于 `metadata`。

本 change 把 `DOCUMENT_HYBRID` 变成第一个真实 Retriever。它需要同时解决检索算法、请求级访问过滤、LangGraph 动态跳转和并行结果写入 state，且不能提前引入尚未实现的 SQL/Graph 节点。

## Goals / Non-Goals

**Goals:**

- 并行执行 Elasticsearch Dense 和 BM25 文档检索。
- 使用确定性 RRF 按 `chunkId` 融合与去重。
- 对两个通道使用完全相同、服务端提供的访问范围和文档范围过滤。
- 以稳定 `RetrievalOutcome` 写入 Graph state，并为后续多个 Retriever 并行写入提供 reducer。
- 让 Query Router 只跳转到真实注册的 `document_hybrid` 节点。
- 通过离线 fake 测试与显式 Elasticsearch 集成测试证明纵向链路。

**Non-Goals:**

- 不实现 Document Rerank 或多查询扩展。
- 不构建最终 EvidencePackage 或回答。
- 不实现 SQL、Graph Retriever 或其占位节点。
- 不接入 Chat API、MCP 或 checkpoint。
- 不实现跨 Retriever fallback。

## Decisions

### 1. Retriever 输入显式携带请求级检索范围

`document_hybrid` 从 `RagState` 读取 `standalone_query` 和服务端调用方提供的 `document_retrieval_scope`。scope 至少包含一个允许访问的 `accessibleBy` 值，并可选限制 `docId` 集合。

scope 缺失、为空或非法时节点在访问 Elasticsearch 前失败。Router 的选择只决定是否执行 Retriever，不授予文档权限。

备选方案是在 Retriever 内读取全局用户或 Chat 会话，但这会破坏请求级 RAG Graph 的调用方独立性，也难以离线测试。

### 2. Dense 与 BM25 是一个 Retriever 内部的并行通道

两个通道接收同一查询、同一 filter 和相同候选上限，通过 `asyncio` 并发执行：

```text
document_hybrid
├── dense_search
└── bm25_search
        ↓
      RRF
```

Dense/BM25 不作为 Router 顶层能力。一个普通通道异常时保留另一通道结果并标记 degraded；两个通道都失败时返回 failed outcome。运行时取消和非普通异常继续向外传播。

### 3. 使用固定、确定性的 RRF

第一版使用固定 RRF 常量 `60`，每个通道贡献 `1 / (60 + rank)`。候选按 fused score 降序、最佳通道 rank、`chunkId` 排序，保证并发完成顺序不影响结果。

同一 `chunkId` 只输出一次；融合结果保留 Dense/BM25 原始 rank 和 score 作为诊断，但不把不同通道的原始 score 直接相加或比较。

备选方案是直接归一化原始 score，但 Dense 相似度和 BM25 分数不共享同一量纲。

### 4. 检索参数在装配时注入

每通道候选数、最终候选数和 timeout 由不可变 `DocumentRetrievalOptions` 在 Graph 装配时注入，domain import 不读取 Settings。第一版使用稳定默认值并在入口装配，后续可映射为配置项。

### 5. Elasticsearch mapping 明确支持三种访问方式

同一索引继续承载写入与检索：

- `text`：BM25 全文检索；
- `vector`：Dense 检索；
- `metadata.docId`、`metadata.chunkId`、`metadata.accessibleBy`：精确过滤和来源定位。

新索引创建时显式声明这些字段。现有索引 mapping 不兼容时启动/装配应明确失败，而不是无过滤检索；部署时需要重建或 reindex 现有开发索引。

### 6. 使用类型化 outcome 和按 Retriever ID 合并的 reducer

`document_hybrid` 输出：

```text
RetrievalOutcome
├── retriever_id = DOCUMENT_HYBRID
├── status = SUCCESS | EMPTY | FAILED
├── candidates
└── diagnostics
    ├── duration_ms
    ├── dense_count
    ├── bm25_count
    ├── result_count
    └── failed_channels
```

`RagState.retrieval_outcomes` 使用确定性 reducer 按 `retriever_id` 合并，并拒绝同一 superstep 中同一 Retriever 的重复写入。state 只保存可序列化数据，不保存 ES client、embedding model 或异常对象。

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

- [现有 Elasticsearch mapping 不兼容精确过滤] → fail closed，并在部署时重建或 reindex 索引。
- [并行通道增加一次请求的 ES 负载] → 限制每通道候选数、最终候选数和 timeout。
- [单通道失败降低召回质量] → outcome 明确标记 degraded channel，便于观测和后续回答策略使用。
- [当前 Router 在生产只看到一个能力] → 这是首个真实 Retriever 的阶段性结果；后续 SQL/Graph change 从注册节点扩展能力集合。
- [当前 collect 后没有最终回答] → 本 change 只证明检索纵向链路，EvidencePackage 和回答属于后续 change。

## Migration Plan

1. 部署前检查目标 Elasticsearch 索引 mapping。
2. mapping 不兼容时重建或 reindex 文档向量索引，并重新执行已有文档的向量存储。
3. 先运行显式 Elasticsearch 集成测试，再启用新的 RAG Studio Graph。
4. 回滚时恢复旧 Graph Builder；保留新增 mapping 不影响旧向量写入。

## Open Questions

无。Document Rerank、EvidencePackage 和跨 Retriever fallback 在后续 change 中决策。
