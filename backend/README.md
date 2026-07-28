# ke-engine backend

## Langfuse 与 LangGraph Studio

在 `.env` 中设置 `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、
`LANGFUSE_BASE_URL`、`LANGFUSE_TRACING_ENVIRONMENT`，并可选设置
`LANGFUSE_RELEASE`。当前实现允许 Langfuse 保存完整用户消息、Prompt、模型输入输出和
业务理解结构化结果。

- 启动带 Langfuse tracing 的 Chat API：
  `uv run uvicorn app.entrypoints.chat_api:app --reload`
- 启动本地 Agent Server，并从终端给出的地址打开 Studio：
  `uv run --extra dev langgraph dev`
- 显式 upsert 本地 Dataset case（不运行模型）：
  `uv run python -m app.evaluation.upsert_business_understanding_dataset`
- 读取 Langfuse 当前 Dataset 并串行运行真实模型 Experiment（不写 Dataset）：
  `uv run python -m app.evaluation.business_understanding_langfuse`

Chat API 和 Studio 的 Langfuse 接入是 fail-open：配置缺失或追踪失败不会改变业务结果。
评测命令是显式操作并采用 fail-fast：配置、认证、网络或 Dataset Run 创建失败时返回非零
退出码。默认测试不会访问 Langfuse 或模型服务；真实评测只由上面的命令手动触发。

## 文档 RAG MCP 最短演示

当前闭环只包含文档 RAG，不包含 SQL/DB 和 GraphDB Retriever。RAG MCP 无鉴权，
固定监听 `http://127.0.0.1:8002/mcp`；Chat 仅通过 `rag_mcp_url` 调用它。

1. 在仓库根目录启动基础设施并初始化数据库：

   ```powershell
   make dev-all-infra
   make db-init
   make kafka-topics-init
   ```

2. 启动 Document API、文档 worker，并上传文档。上传时让
   `accessibleBy` 包含 `mock-user`，再等待文档完成切分和向量写入。

   ```powershell
   make dev-document-api
   make dev-worker
   ```

3. 分别启动 RAG MCP 和 Chat API：

   ```powershell
   make dev-rag-mcp
   make dev-chat-api
   ```

4. 显式运行真实闭环 smoke：

   ```powershell
   cd backend
   uv run python scripts/smoke_chat_rag.py "调度规程对超限货物列车编组有什么要求？"
   ```

知识类 intent 会执行
`Chat -> retrieve_evidence MCP -> Query Rewrite -> Hybrid Retrieval -> Rerank -> Grounded Answer`。
`BUSINESS_DATA_QUERY` 和 `OTHER_BUSINESS` 仍返回未接入边界提示。MCP 服务没有额外
健康检查、鉴权、重试或熔断配置。
