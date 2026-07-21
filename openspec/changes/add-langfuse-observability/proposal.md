## Why

现有 Chat LangGraph 已能稳定执行和持久化，但开发者缺少一次 completion 内 Graph、节点、Prompt 和模型调用的统一观察入口，也无法在 Studio 中直接调试当前图。已有 18 条业务理解用例只有离线确定性自校验，尚不能运行真实模型并在 Langfuse 中比较实验结果。

## What Changes

- 接入 Langfuse Python SDK，为每个已接受的 Chat completion 创建应用级根 trace，并通过 LangChain callback 记录现有 Graph、节点与模型调用。
- Langfuse 在 Chat API 和 Studio 中均为 fail-open；配置、初始化、上报或关闭失败不改变业务执行结果。
- 允许记录完整消息、Prompt、模型输入输出和结构化结果，不增加采样、脱敏或 tracing 启停开关。
- 增加极薄的 LangGraph Studio adapter，为现有唯一 graph builder 绑定开发模型，不复用生产 FastAPI lifespan。
- 将现有 18 条业务理解 fixture 幂等同步到 Langfuse Dataset，串行运行真实业务理解节点并记录五项确定性 Scores。
- 增加 Langfuse、LangGraph CLI 依赖和本地运行说明。

## Capabilities

### New Capabilities

- `langfuse-observability`: Chat completion 根 trace、LangGraph/LangChain 子 observations、原始内容采集和 fail-open 生命周期行为。
- `business-understanding-evaluation`: 18 条 fixture 的 Langfuse Dataset 映射、真实模型 Experiment 和五维确定性评分。

### Modified Capabilities

- `chat-langgraph-runtime`: 增加复用唯一 graph builder 的本地 Studio 运行方式，同时保持生产 runtime context 和 PostgreSQL checkpointer 装配不变。

## Impact

- 后端增加 Langfuse 运行依赖和 LangGraph CLI 开发依赖。
- Chat API lifespan、依赖对象、Router 和 `CompletionProducer` 增加可选 Langfuse 接线。
- Chat graph builder 和两个模型节点增加开发模型预绑定入口，但不改变节点名称、状态、边或 `Command(goto)` 路由。
- 新增 Studio `langgraph.json`、评测 CLI、聚焦测试和 README 命令。
- 不改变公开 HTTP/SSE 契约、数据库 schema、Redis 锁协议或 checkpoint 一致性边界。
