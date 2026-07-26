## 1. 检索契约与索引约束

- [x] 1.1 先编写离线单元测试，覆盖请求级 scope、Candidate、`RetrievalOutcome`、不可变检索选项及按 Retriever ID 合并的 reducer
- [x] 1.2 实现可序列化的文档检索契约与 reducer，并拒绝缺失访问范围及重复 Retriever outcome
- [x] 1.3 先补充 Elasticsearch mapping 测试，覆盖 `text`、`vector`、`metadata.docId`、`metadata.chunkId`、`metadata.accessibleBy` 及不兼容 mapping
- [x] 1.4 更新 Elasticsearch 索引创建与兼容性校验，确保不兼容或缺少访问过滤字段时 fail closed

## 2. LangChain Elasticsearch Hybrid Retriever

- [ ] 2.1 先编写离线单元测试，证明应用层 RRF 按 `chunkId` 融合、去重、确定性排序并按结果上限截断
- [ ] 2.2 实现自定义 LangChain `BaseRetriever`，异步并行执行 Elasticsearch BM25 与 `ElasticsearchStore` KNN，并保持同步调用兼容
- [x] 2.3 实现服务端 scope 到 Elasticsearch `terms` filters 的转换，并测试 `accessibleBy` 必填及可选 `docId`
- [ ] 2.4 实现请求级 Retriever factory，绑定共享 client/store、不可变 scope、候选数、结果数和固定 `rank_constant=60`
- [ ] 2.5 测试 BM25/KNN 使用相同 filters、向量 Store 禁用原生 Hybrid/RRF，任一路失败时整体失败

## 3. RAG Graph 动态路由与检索节点

- [x] 3.1 先更新 Router 与 Graph 测试，证明可用能力由实际注册节点生成，且未实现的 SQL/Graph 节点不会被暴露
- [x] 3.2 修改 Query Router，使其在写入 `retrieval_plan` 的同时通过 LangGraph `Command` 跳转到已注册的 Retriever
- [ ] 3.3 验证 `document_hybrid` node 通过 `ainvoke` 调用请求级自定义 `BaseRetriever`、传播 Runnable config 并转换 LangChain Documents
- [x] 3.4 测试并实现 Hybrid 请求成功、空结果、普通依赖失败、timeout 和取消传播语义
- [x] 3.5 将 `retrieval_outcomes` reducer、`document_hybrid` 和 `collect_retrieval_outcomes` 接入 Graph Builder
- [x] 3.6 实现 collector 完整性校验，确保计划中的每个 Retriever 都产生一个 outcome
- [ ] 3.7 更新 Studio/入口装配，注入共享 client、向量 store、请求级自定义 Retriever factory 和检索选项，同时保持 Graph 无 checkpointer

## 4. 纵向验证

- [x] 4.1 添加默认离线纵向测试，覆盖 `query_rewrite -> query_router -> document_hybrid -> collect_retrieval_outcomes`
- [x] 4.2 添加脱敏诊断测试，只记录请求耗时与结果数，不暴露连接信息、原始异常或未授权 metadata
- [ ] 4.3 更新显式 Elasticsearch 集成测试，覆盖真实 BM25/KNN、应用层 RRF、ACL/docId filters、空结果、mapping 及 Basic License 兼容性，并确保默认测试不隐式运行
- [ ] 4.4 运行相关格式化、类型检查和默认离线测试，修复所有回归
- [ ] 4.5 在开源版 Elasticsearch 上运行显式集成测试，并记录 Elasticsearch 版本/许可证与索引重建或 reindex 前置条件
- [ ] 4.6 运行 `openspec validate add-rag-hybrid-document-retrieval --type change --strict` 并确认 Change 全部 artifact 完成
