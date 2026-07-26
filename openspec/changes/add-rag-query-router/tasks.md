## 1. Router 契约与 Prompt

- [x] 1.1 先新增 `RetrieverKind`、`QueryRouterInput`、`QueryRouteResult`、`RetrievalPlan` 和 update/error 契约测试，再实现严格 Pydantic 模型与公开导出
- [x] 1.2 先新增能力边界、最小充分多选、反关键词误判和输出禁令的 Prompt 测试，再实现版本化 Query Router Prompt

## 2. Router 节点

- [x] 2.1 先新增单选、多选、重复项规范化、固定顺序和 callback 透传测试，再实现结构化模型调用及计划规范化
- [x] 2.2 先新增普通异常、超时、非法结构、空选择、未知或不可用能力的 fallback 测试，再实现仅回退 `DOCUMENT_HYBRID` 且不重试的逻辑
- [x] 2.3 新增无安全 fallback 时的稳定异常测试，以及运行时取消不被转换为 fallback 的测试

## 3. RAG Graph 集成

- [x] 3.1 扩展 `RagState` 保存可序列化 `retrieval_plan`，并更新 RAG domain/node 的公开导出
- [x] 3.2 更新 Builder 注入非空可路由能力并绑定 `query_router`，使拓扑精确为 `START -> query_rewrite -> query_router -> END`
- [x] 3.3 更新 Graph、Studio 和现有 Query Rewrite 测试，证明无 checkpointer、无动态 `goto`、请求隔离及 callback 透传行为保持成立

## 4. 离线与真实模型评测

- [ ] 4.1 新增仓库 Router fixture，覆盖三类单选、三种双选、三选、关键词反例和能力受限案例
- [ ] 4.2 实现离线路由集合 evaluator，并用测试覆盖完全匹配、过度路由和遗漏路由
- [ ] 4.3 新增显式 Langfuse Dataset/Experiment 入口及其离线测试，确保默认 pytest 不访问网络且真实评测调用生产 RAG Graph

## 5. 验证

- [ ] 5.1 运行 Query Router 与 RAG Graph 聚焦测试，并修复全部回归
- [ ] 5.2 运行 backend 全量非集成测试和 OpenSpec strict validation，记录验证结果
