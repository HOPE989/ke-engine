## 1. 检索契约与索引约束

- [ ] 1.1 先编写离线单元测试，覆盖 `BaseRetriever` 继承契约、同步/异步调用、callback 传播、请求级 scope、候选项、`RetrievalOutcome`、不可变检索选项及按 Retriever ID 合并的 reducer
- [ ] 1.2 实现可序列化的文档检索契约与 reducer，并拒绝缺失访问范围及重复 Retriever outcome
- [ ] 1.3 先补充 Elasticsearch mapping 测试，覆盖 `text`、`vector`、`metadata.docId`、`metadata.chunkId`、`metadata.accessibleBy` 及不兼容 mapping
- [ ] 1.4 更新 Elasticsearch 索引创建与兼容性校验，确保不兼容或缺少访问过滤字段时 fail closed

## 2. Elasticsearch 文档检索通道

- [ ] 2.1 实现继承 LangChain `BaseRetriever` 的 `HybridDocumentRetriever` 骨架，组合现有 `ElasticsearchStore`、Elasticsearch client 和 Embedding Model
- [ ] 2.2 实现 Retriever factory，为每次请求绑定不可变授权 scope，并拒绝使用可变的进程级 filter
- [ ] 2.3 实现 Dense 文档搜索，使用请求级访问范围、可选文档范围、候选上限和 timeout
- [ ] 2.4 实现 BM25 文档搜索，并应用与 Dense 完全相同的请求级过滤条件、候选上限和 timeout
- [ ] 2.5 为两个通道补充离线 fake 测试，验证查询映射、授权过滤、空结果和标准 LangChain `Document` 来源字段

## 3. 混合检索与结果融合

- [ ] 3.1 先编写确定性 RRF 测试，覆盖跨通道去重、单通道候选、稳定排序、并发完成顺序和最终候选预算
- [ ] 3.2 实现固定常量为 60 的 RRF，按 `chunkId` 去重并保留各通道 rank/score 诊断
- [ ] 3.3 在 `_aget_relevant_documents` 中实现 Dense 与 BM25 并发执行，并补齐同步 `_get_relevant_documents` 契约
- [ ] 3.4 测试并实现单通道降级、双通道失败、双通道空结果和取消传播语义
- [ ] 3.5 添加脱敏诊断，记录耗时、通道候选数、融合结果数和失败通道，不暴露连接信息或原始异常

## 4. RAG Graph 动态路由与汇合

- [ ] 4.1 先更新 Router 与 Graph 测试，证明可用能力由实际注册节点生成，且未实现的 SQL/Graph 节点不会被暴露
- [ ] 4.2 修改 Query Router，使其在写入 `retrieval_plan` 的同时通过 LangGraph `Command` 跳转到已注册的 Retriever
- [ ] 4.3 实现 `document_hybrid` node，通过 `ainvoke` 调用 Retriever、将 LangChain `Document` 转换为 Candidate/`RetrievalOutcome`，并传播 Runnable config
- [ ] 4.4 将 `retrieval_outcomes` reducer、`document_hybrid` 和 `collect_retrieval_outcomes` 接入 Graph Builder
- [ ] 4.5 实现 collector 完整性校验，确保计划中的每个 Retriever 都产生一个 outcome
- [ ] 4.6 更新 Studio/入口装配，注入请求级 Retriever factory 和检索选项，同时保持 Graph 无 checkpointer

## 5. 纵向验证

- [ ] 5.1 添加默认离线纵向测试，覆盖 `query_rewrite -> query_router -> document_hybrid -> collect_retrieval_outcomes`
- [ ] 5.2 添加显式 Elasticsearch 集成测试，覆盖 Dense、BM25、metadata 过滤、RRF、空结果和 mapping 兼容性，并确保默认测试不隐式运行
- [ ] 5.3 运行相关格式化、类型检查和默认离线测试，修复所有回归
- [ ] 5.4 运行显式 Elasticsearch 集成测试，并记录测试索引重建或 reindex 前置条件
- [ ] 5.5 运行 `openspec validate add-rag-hybrid-document-retrieval --type change --strict` 并确认 Change 全部 artifact 完成
