## 1. 检索契约与索引约束

- [x] 1.1 先编写离线单元测试，覆盖请求级 scope、Candidate、`RetrievalOutcome`、不可变检索选项及按 Retriever ID 合并的 reducer
- [x] 1.2 实现可序列化的文档检索契约与 reducer，并拒绝缺失访问范围及重复 Retriever outcome
- [x] 1.3 先补充 Elasticsearch mapping 测试，覆盖 `text`、`vector`、`metadata.docId`、`metadata.chunkId`、`metadata.accessibleBy` 及不兼容 mapping
- [x] 1.4 更新 Elasticsearch 索引创建与兼容性校验，确保不兼容或缺少访问过滤字段时 fail closed

## 2. LangChain Elasticsearch Hybrid Retriever

- [x] 2.1 先编写基础设施测试，证明 retrieval store 使用 `DenseVectorStrategy(hybrid=True)`、固定 `rank_constant=60` 和注入的 rank window
- [x] 2.2 装配复用现有 client、index 和 Embedding Model 的 Hybrid `ElasticsearchStore`
- [x] 2.3 实现服务端 scope 到 Elasticsearch `terms` filters 的转换，并测试 `accessibleBy` 必填及可选 `docId`
- [x] 2.4 实现请求级 Retriever factory，通过 `store.as_retriever()` 绑定结果限制和不可变授权 filters
- [x] 2.5 测试 LangChain 生成的原生 Hybrid 查询同时包含 `match(text)`、KNN、相同 filters 和 RRF 参数

## 3. RAG Graph 动态路由与检索节点

- [ ] 3.1 先更新 Router 与 Graph 测试，证明可用能力由实际注册节点生成，且未实现的 SQL/Graph 节点不会被暴露
- [ ] 3.2 修改 Query Router，使其在写入 `retrieval_plan` 的同时通过 LangGraph `Command` 跳转到已注册的 Retriever
- [ ] 3.3 实现 `document_hybrid` node，通过 `ainvoke` 调用请求级 `VectorStoreRetriever`、传播 Runnable config 并转换 LangChain Documents
- [ ] 3.4 测试并实现 Hybrid 请求成功、空结果、普通依赖失败、timeout 和取消传播语义
- [ ] 3.5 将 `retrieval_outcomes` reducer、`document_hybrid` 和 `collect_retrieval_outcomes` 接入 Graph Builder
- [ ] 3.6 实现 collector 完整性校验，确保计划中的每个 Retriever 都产生一个 outcome
- [ ] 3.7 更新 Studio/入口装配，注入 Hybrid store、请求级 Retriever factory 和检索选项，同时保持 Graph 无 checkpointer

## 4. 纵向验证

- [ ] 4.1 添加默认离线纵向测试，覆盖 `query_rewrite -> query_router -> document_hybrid -> collect_retrieval_outcomes`
- [ ] 4.2 添加脱敏诊断测试，只记录请求耗时与结果数，不暴露连接信息、原始异常或未授权 metadata
- [ ] 4.3 添加显式 Elasticsearch 集成测试，覆盖 BM25/KNN Hybrid、ACL/docId filters、原生 RRF、空结果、mapping 及目标集群能力，并确保默认测试不隐式运行
- [ ] 4.4 运行相关格式化、类型检查和默认离线测试，修复所有回归
- [ ] 4.5 运行显式 Elasticsearch 集成测试，并记录 Elasticsearch 版本/许可证与索引重建或 reindex 前置条件
- [ ] 4.6 运行 `openspec validate add-rag-hybrid-document-retrieval --type change --strict` 并确认 Change 全部 artifact 完成
