## 1. 子 Change：收口 RAG 输出

- [x] 1.1 为 `RetrieveEvidenceRequest`、`EvidenceItem` 和 `EvidencePackage` 编写契约测试，覆盖非空 query、`accessibleBy`、可选上下文、字段别名和 JSON 可序列化
- [x] 1.2 实现文档专用的最小 RAG 请求、证据项和证据包 Pydantic 模型，不加入 SQL、Graph、Trace 或完整诊断字段
- [x] 1.3 为 `retrieve_evidence` 应用服务编写 fake compiled-graph 测试，覆盖 `SUCCESS` 投影、`EMPTY` 空包、`FAILED` 失败和稳定 citation ID
- [x] 1.4 实现 `retrieve_evidence` 应用服务，调用现有 RAG Graph 并把 `retrieval_outcomes` 投影为 EvidencePackage
- [x] 1.5 增加领域边界测试，证明 EvidencePackage 不泄露 Graph state、客户端对象、凭据、原始异常或完整阶段诊断

## 2. 子 Change：暴露 RAG MCP

- [x] 2.1 向 backend 添加有 major 上界的官方 MCP Python SDK 依赖并更新锁文件
- [x] 2.2 为 MCP Server 编写协议级测试，验证只发现 `retrieve_evidence`、合法请求返回 structured output、非法请求不调用应用服务
- [x] 2.3 实现 `services/rag_mcp` 适配层，注册无鉴权的 `retrieve_evidence` Tool 并委托普通 Python 应用服务
- [x] 2.4 抽取可被 Studio 与 MCP entrypoint 复用的 RAG Graph 资源装配，复用现有模型、Embedding、Elasticsearch、Reranker、父块缓存和可选 Langfuse
- [x] 2.5 实现固定本地 host/port 的 `entrypoints/rag_mcp.py` Streamable HTTP 启动入口，不增加 FastAPI、健康检查或额外服务配置
- [x] 2.6 在 Makefile 增加最小 `dev-rag-mcp` 启动命令，并用测试证明入口和命令可被加载
- [x] 2.7 增加使用真实 Streamable HTTP transport 和 fake retrieval service 的 MCP list/call 集成测试，证明客户端能完成 initialize、Tool discovery 和 structured result 解析

## 3. 子 Change：Chat 通过 MCP 完成证据化回答

- [x] 3.1 定义与 MCP SDK 解耦的 `RagClient` 协议，并为生产 MCP Client 适配器编写请求序列化、Tool 结果解析和调用失败测试
- [x] 3.2 实现 Chat 侧 MCP Client 适配器，只新增 `rag_mcp_url` Settings 字段并在 Chat lifespan 中装配客户端
- [x] 3.3 扩展 `ChatRuntimeContext` 和 `ChatState`，通过 runtime 注入 `rag_client`、当前 user ID，并只在 state 保存可序列化 evidence package 与 references
- [x] 3.4 为 Business Understanding intent 路由编写 Graph 测试，证明四类文档知识 intent 进入 `knowledge_rag`，`BUSINESS_DATA_QUERY` 与 `OTHER_BUSINESS` 保持边界响应
- [x] 3.5 实现 `knowledge_rag` 节点，提取当前问题、最近十条历史消息、业务 intent 和 `accessibleBy=[user_id]` 后调用 RagClient
- [x] 3.6 为 Grounded Answer Prompt 和节点编写测试，覆盖编号证据、只基于证据回答、空证据固定文本和 MCP 失败传播
- [x] 3.7 实现 `grounded_answer` 节点与目标 Chat Graph 拓扑，并同步更新 Studio 的显式 RagClient 注入方式
- [x] 3.8 扩展 completion 事件投影，使 `grounded_answer` 的模型流和空证据固定文本继续使用现有 `content_delta`，且不暴露 MCP/LangGraph 原始事件
- [x] 3.9 扩展 Graph completion 收集逻辑，在成功到达 END 后读取本轮最终 `rag_references`，并保持失败时不提交部分回答
- [x] 3.10 扩展 `MessageRepository.add_assistant`，在同一事务中保存完整回答和引用，并验证非 RAG 消息仍保存空数组
- [x] 3.11 扩展 `MessageSummary` 和消息历史投影返回 `rag_references`，覆盖有引用与无引用消息

## 4. 子 Change：端到端扫尾与验证

- [x] 4.1 增加 Chat Graph fake-RagClient 纵向测试，证明知识请求依次完成 MCP 客户端调用、Grounded Answer、SSE 投影和引用持久化
- [x] 4.2 增加可显式运行的本地 live smoke 测试或脚本，使用已上传且 `accessibleBy` 等于 mock user ID 的真实文档验证 `Chat -> MCP -> Elasticsearch -> Rerank -> Answer`
- [x] 4.3 更新服务入口、配置和演示文档，给出启动基础设施、RAG MCP、Chat API 和发起文档知识问题的最短命令序列
- [x] 4.4 运行 RAG、Chat、服务入口和配置聚焦测试，修复回归后运行 backend 默认非集成测试
- [x] 4.5 运行 `openspec validate complete-document-rag-mcp-integration --strict`，确认 proposal、design、五份 delta spec 和任务状态一致且 apply-ready
