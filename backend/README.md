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
