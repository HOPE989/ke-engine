# Langfuse 可观测性、Studio 与业务理解评测设计

**日期：** 2026-07-22
**状态：** 已确认，待实现

## 目标

在不改变 Chat 业务语义的前提下，为现有 LangGraph 运行时接入 Langfuse，并提供两个开发入口：

- 生产和开发 Chat completion 的完整 Langfuse trace；
- 极薄的 LangGraph Studio 本地调试入口；
- 基于现有 18 条 business-understanding fixture 的真实模型 Langfuse Experiment。

本次首先解决“看清一次图执行”和“看懂一次离线评测”两个问题，不建设通用可观测平台或通用评测框架。

## 范围

本次实现：

- 使用当前 Langfuse Python SDK 和 LangChain callback 追踪 completion、Graph、节点与模型调用；
- 记录完整用户消息、Prompt、模型输入输出和结构化业务理解结果；
- 以 `conversation_id` 关联同一会话，以 `user_id` 关联用户；
- Langfuse 初始化、上报和关闭全部 fail-open；
- 使用现有 `build_chat_graph()` 作为唯一图拓扑来源；
- 增加仅供本地调试的 Studio adapter 和 `langgraph.json`；
- 将现有 18 条 fixture 同步到 Langfuse Dataset，运行真实模型 Experiment，并产生五维确定性 Scores；
- 提供简短命令和环境变量说明。

本次不实现：

- Langfuse Prompt Management；
- LLM-as-a-Judge、在线 Evaluator、Annotation Queue 或 CI 质量门禁；
- 跨模型批量比较、参数矩阵或并发压测；
- 自动从生产 trace 回流 Dataset；
- 数据脱敏、采样或关闭原始输入输出采集的开关；
- Studio 对 FastAPI lifespan、业务数据库、Redis、分布式锁、Registry 或 SSE 的复刻；
- 通用 tracing provider、插件体系或与 LangSmith tracing 并存的抽象层。

## 核心决策

### 使用具体的 Langfuse 接入，不建设通用可观测抽象

新增的基础设施代码只封装 Langfuse 的资源创建、completion trace 和安全关闭。它不定义 provider protocol、factory registry、通用 span 模型或可替换后端。

这层窄封装仅解决两个实际问题：FastAPI 与 Studio 需要复用同一套 Langfuse 初始化方式；观测代码的异常必须和业务异常严格隔离。领域节点仍通过标准 LangGraph/LangChain callback 被追踪，不依赖自定义观测接口。

### 一个 completion 对应一个应用级根 trace

`CompletionProducer.run()` 是一次已接受用户轮次的完整执行边界，覆盖 Graph 执行、澄清中断、ASSISTANT 落库和终态事件，因此在这里建立名为 `chat-completion` 的根 observation。

根 trace 记录：

- input：完整本轮用户内容及稳定业务标识；
- `session_id`：`conversation_id`；
- `user_id`：当前认证用户；
- metadata：`conversation_id`、`user_message_id`、模型、应用版本、输入模式 `new`/`resume`；
- output：完整最终文本、`finish_reason` 与终态 `completed`/`error`；
- tags：`chat`、`langgraph` 和运行来源。

Graph 调用在根 observation 的活动上下文中执行，并在 `RunnableConfig.callbacks` 中加入 Langfuse `CallbackHandler`。LangGraph、节点、结构化模型调用和普通 LLM 调用由 callback 形成子 observations。`propagate_attributes()` 把会话、用户和短 metadata 传播到子 observations。

不把每个 SSE delta 建成单独 observation，也不追踪 Redis lock token、SQL、原始 checkpoint 序列化或 title model，避免 trace 被基础设施噪声淹没。

### 原始内容始终允许采集

开发、测试和生产环境均允许 Langfuse 保存完整用户消息、完整 Prompt、模型输入、模型输出和结构化结果。生产为内网自部署，因此本次不增加脱敏、采样或关闭内容采集的配置。

密钥、数据库 URL、Redis URL 和锁 token 不作为 trace 数据主动写入。

### Langfuse 必须 fail-open

Langfuse 不是业务正确性的依赖：

- 缺少或无效的 Langfuse 配置时，Chat API 与 Studio 仍可启动和运行；
- client、handler 或根 observation 创建失败时，记录一次日志并无追踪执行；
- callback、根 observation 更新、flush 或 shutdown 失败时，只记录日志；
- Graph、checkpoint、Redis、业务数据库和 SSE 的异常语义保持不变；
- 观测清理失败不得覆盖原始业务异常，也不得把成功 completion 改成 error。

Langfuse SDK 自身会对异步上报做缓冲和重试，但应用仍在接入边界隔离同步初始化或使用错误。FastAPI lifespan 关闭时在 producer registry 停止之后 best-effort shutdown Langfuse，确保已完成 trace 尽量发出。

### 使用 Langfuse 标准环境变量

不增加 `enabled` 开关。现有 `backend/.env` 由 Pydantic Settings 读取而不会自动写回进程环境，因此在 `Settings` 中声明对应字段，并把值显式传给 Langfuse SDK：

- `LANGFUSE_PUBLIC_KEY`；
- `LANGFUSE_SECRET_KEY`；
- `LANGFUSE_BASE_URL`；
- `LANGFUSE_TRACING_ENVIRONMENT`；
- `LANGFUSE_RELEASE`。

`.env.example` 补充说明性占位。public key、secret key 或 base URL 缺失时，生产 Chat 与 Studio 按 fail-open 进入无追踪路径；环境和 release 分别默认使用应用环境与 `app_version`。

## 生产运行数据流

1. Chat API lifespan 创建业务数据库、模型、PostgreSQL saver 与 Redis 等现有资源。
2. lifespan best-effort 创建 Langfuse client 和 `CallbackHandler`，并把它们作为可选依赖放入 `ChatApiDeps`。
3. Router 创建 `CompletionProducer` 时传入这两个具体依赖，不新增 provider/factory 链路。
4. Producer 发布 metadata 后进入 `chat-completion` 根 observation；初始化失败则进入等价的无追踪路径。
5. Producer 判断本轮是新输入还是 `Command(resume=...)`，并写入 trace metadata。
6. `astream_events()` 继续使用现有 `ChatRuntimeContext(model=...)`，同时把可选 callback 放入 config。
7. callback 自动记录现有 Graph、节点、Prompt、模型调用、Token、耗时和异常；`Command(goto)` 形成的实际节点路径可在 trace 中观察。
8. Producer 保存 ASSISTANT 消息并发布 terminal event 后，用最终内容、终止原因和状态结束根 observation。
9. 应用关闭时先等待 producer registry，再 best-effort 关闭 Langfuse，最后按现有顺序释放 Redis、saver 和业务数据库。

现有 conversation Redis 锁的获取、持有和释放范围不变；Langfuse 不参与锁判断。

## Studio 设计

### 复用唯一图拓扑

`builder.py` 继续是图结构、节点名称、边和 `Command(goto)` 行为的唯一来源。Studio 不复制节点注册或边声明。

生产调用保持为：

```python
build_chat_graph().compile(checkpointer=saver)
```

Studio adapter 调用概念上为：

```python
build_chat_graph(bound_model=studio_model).compile()
```

`bound_model` 模式只解决 Agent Server 无法通过 JSON runtime context 注入 `BaseChatModel` 的问题：builder 为两个依赖模型的节点绑定 Studio 模型，并使用不包含 `BaseChatModel` 的 Studio context schema。节点核心逻辑、状态结构和全部拓扑仍是现有实现。

生产默认模式仍使用 `ChatRuntimeContext` 注入模型，避免 Studio 方案改变 FastAPI 运行时资源所有权。

### 极薄 adapter

`app/entrypoints/studio_graph.py` 只做以下事情：

1. 读取现有模型和 Langfuse 配置并创建一个 Chat model；
2. best-effort 创建 Langfuse handler；
3. 调用带 bound model 的现有 builder；
4. 导出供 `langgraph.json` 引用的 Graph。

它不启动 FastAPI，不创建 title model、业务 Session、Redis、分布式锁或 producer registry，也不加载生产 PostgreSQL saver。`langgraph dev` 的 Agent Server 使用自己的开发期 persistence。

Studio 是个人调试工具，只增加 `langgraph-cli[inmem]` 开发依赖和一条启动命令，不增加自定义 lifespan、部署脚本、鉴权或工程化运维措施。

## Business Understanding Langfuse Experiment

### 为什么使用 Langfuse Dataset

Langfuse SDK 可以直接对本地数据运行 experiment，但本地数据只创建 traces，不创建可在 Dataset 页面横向比较的 Dataset Run。为让第一次接触评测时能在 UI 中直观看到“同一批用例的多次运行和分数变化”，本次将 18 条现有 fixture 同步为 Langfuse 托管 Dataset。

固定 Dataset 名称为 `ke-engine/business-understanding-v1`。本地 JSON 仍是代码仓库里的事实来源，Langfuse Dataset 是用于运行和展示的副本。

### Dataset 映射

每条 `EvaluationCase` 映射为：

- item id：由项目名、Dataset 版本与现有 case id 生成的稳定 ID，用于重复执行时 upsert；
- input：`{"messages": [...]}`，保留完整多轮角色和内容；
- expected output：`route`、`intent`、`key_entities`、`clarification_contains`；
- metadata：`case_id`、`category`、`prompt_version`。

命令每次运行先确保 Dataset 存在，再按稳定 item id upsert 当前 18 条数据。本次不自动删除或归档 Langfuse 中已经存在但本地后来移除的 item；数据集结构发生实质变化时通过新的 Dataset 版本名显式演进。

### Experiment task

评测 task 不调用 FastAPI，也不跑整条回答图。它把 fixture messages 转成 LangChain messages，使用当前配置创建真实 Chat model，然后直接调用现有 `business_understanding_node`，从返回的 `Command.update["business_understanding"]` 取得结构化实际输出。

这样测试对象就是当前生产业务理解节点及其 Prompt、Schema 和真实模型，同时避开 Redis、checkpoint、业务数据库、SSE 和后续 placeholder 节点。

默认 `max_concurrency=1`，便于阅读 trace、降低模型限流噪声，也避免为首版评测引入并发控制。

### Scores

复用现有 `score_evaluation_cases()`，通过一个 Langfuse evaluator 一次返回五个 `Evaluation`：

- `route_accuracy`：路由是否精确匹配；
- `intent_accuracy`：意图是否精确匹配，包括预期 `null`；
- `key_entity_recall`：期望关键实体命中数除以期望实体数；无期望实体时记为 1；
- `clarification_accuracy`：应澄清时是否包含期望关键词，不应澄清时是否为 `null`；
- `schema_validity`：是否通过 `BusinessUnderstandingResult` 校验。

分数均为 0 到 1 的 numeric score，并在 comment/metadata 中保留命中分子分母，方便从汇总下钻到失败用例。真实模型失败由 Experiment runner 隔离在单条 item，不伪造成 0 分结构化输出。

Experiment run name 默认包含时间，metadata 记录模型名、Prompt 版本、应用版本和 `live_model=true`。命令结束时打印 `result.format()` 和 Langfuse Dataset Run URL，并显式 flush/shutdown，适合短生命周期 CLI。

生产 tracing 的 fail-open 不适用于这个显式评测命令：缺少 Langfuse 凭据、Dataset 同步失败或无法访问 Langfuse 时，CLI 以清晰错误和非零退出码结束，避免用户误以为已经产生 Dataset Run。单条模型任务失败仍由 Experiment runner 隔离并展示。

### 首版明确边界

五项分数是可解释的确定性契约指标，不代表回答质量、业务事实正确性或泛化能力。本次不设置合格阈值，不阻断提交或部署，也不使用另一个模型裁判。用户先通过 Langfuse UI 观察实际结果，再决定是否增加样例、LLM-as-a-Judge、人工标注或 CI 门禁。

## 预计文件边界

- `backend/pyproject.toml`：增加 Langfuse 运行依赖和 Studio 开发依赖；
- `backend/.env.example`：补充 Langfuse 标准环境变量；
- `backend/app/core/config.py`：增加 Langfuse 标准连接字段，不增加启停开关；
- `backend/app/infrastructure/langfuse.py`：具体的 Langfuse 初始化、completion trace 与关闭辅助；
- `backend/app/services/chat_api/deps.py`：lifespan 资源装配；
- `backend/app/services/chat_api/router.py`：把可选 client/handler 传给 Producer；
- `backend/app/domains/chat/services/runtime.py`：completion 根 trace 和 Graph callback；
- `backend/app/domains/chat/graph/builder.py` 及两个模型节点：支持 Studio bound model，但不复制拓扑；
- `backend/app/entrypoints/studio_graph.py`：极薄 Studio adapter；
- `backend/langgraph.json`：Agent Server 本地图入口；
- `backend/app/evaluation/business_understanding_langfuse.py`：Dataset 同步、真实 task、evaluator 与 CLI；
- 聚焦单测、运行说明和必要的架构约束测试。

文件名可在实现时按项目现有导入边界微调，但不得演化成通用工厂或第二份 Graph。

## 测试策略

### 单元测试

- Langfuse 缺失配置、client 创建失败、handler 创建失败时返回无追踪路径；
- 根 observation 创建、update、flush 或 shutdown 失败不改变 completion 终态；
- 业务异常在记录 trace 后仍保持现有 error event 语义；
- Producer 只在 handler 存在时加入 callback，并保留 `thread_id`；
- trace 的 session/user/metadata/input/output 映射正确；
- bound model builder 继续使用同一节点名称和拓扑，生产 context 模式不变；
- 导入 Studio adapter 不创建数据库、Redis 或生产 saver；
- 18 条 fixture 到 Dataset item 的映射和稳定 ID 正确；
- Langfuse evaluator 将现有五维分子分母正确转换为 0..1 Scores；
- Experiment 使用真实节点 task、单并发和 `live_model=true` metadata。

所有默认单测使用 fake Langfuse client、handler 和 fake model，不访问网络。

### 手动验证

- 配置自部署 Langfuse 后启动 Chat API，完成普通回答和澄清恢复各一次，在 UI 中确认一条根 trace、节点路径、Prompt、结构化输出和模型 generation；
- 停止 Langfuse 后再次完成 Chat 请求，确认业务仍成功；
- 执行 `langgraph dev`，在 Studio 中运行普通、业务和澄清输入，确认使用现有图；
- 执行 business-understanding Experiment 命令，确认 Dataset 有 18 条 item、Dataset Run 可见、五项 Scores 可聚合和下钻。

真实 Langfuse、真实模型和 Agent Server 验证不纳入默认 pytest，避免测试套件依赖网络和产生模型费用。

## 备选方案与取舍

### 复用完整 FastAPI lifespan

拒绝。Agent Server 会额外创建 title model、业务数据库、生产 saver、Redis 和 registry，但这些资源不会自动注入 Studio 图，既重复又扩大调试依赖。

### 复制一份 Studio Graph

拒绝。节点或路由变化后两份拓扑容易漂移，尤其会破坏已经确定的 `Command(goto)` 控制方式。Studio adapter 必须调用唯一 builder。

### 只用本地数据运行 Langfuse Experiment

暂不采用。代码最少，但 Langfuse 当前只为本地数据创建 traces，不创建 Dataset Run，对初次学习 UI 比较能力不够直观。同步一个固定 Dataset 的额外代码有限，且 item id 可幂等 upsert。

### 首版加入 LLM-as-a-Judge

拒绝。当前目标是验证结构化路由契约，五维确定性评分更透明。回答质量和主观语义指标应在观察首轮结果后再设计 rubric。

## 官方资料依据

- [Langfuse LangChain/LangGraph callback 集成](https://langfuse.com/integrations/frameworks/langchain)
- [Langfuse metadata 与 `propagate_attributes`](https://langfuse.com/docs/observability/features/metadata)
- [Langfuse Experiments via SDK](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk)
- [Langfuse Experiment 数据模型](https://langfuse.com/docs/evaluation/experiments/data-model)
- [Langfuse Dataset 管理](https://langfuse.com/docs/evaluation/experiments/datasets)
- [LangGraph 本地 Agent Server 与 Studio](https://docs.langchain.com/oss/python/langgraph/local-server)
- [LangGraph 应用结构与 `langgraph.json`](https://docs.langchain.com/oss/python/langgraph/application-structure)
