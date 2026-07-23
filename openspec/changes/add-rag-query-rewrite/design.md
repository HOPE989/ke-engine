## Context

当前 `backend/app/domains/rag/` 尚未承载具体实现，而项目已经具备 LangChain、LangGraph、模型工厂和 Langfuse callback 基础设施。完整 RAG 链路仍在设计中，但 Query Rewrite 的输入边界、单查询输出、失败降级和与 Router 分离等决策已经稳定。

本 change 先实现一个可独立运行的纵向切片：调用方提供当前问题、裁剪后的原始会话上下文和可选业务上下文，RAG domain 使用注入的 Chat model 生成一条 `standalone_query`，并通过最小 LangGraph 暴露开发期运行入口。该切片未来将直接成为完整 RAG Graph 的第一个业务节点。

## Goals / Non-Goals

**Goals**

- 定义不依赖 Chat domain、会话存储或外部服务的 Query Rewrite 输入输出契约。
- 实现“一对一、受约束的检索化改写”，并保留会改变检索结果的硬约束。
- 提供 `START -> query_rewrite -> END` 的最小 LangGraph，支持 fake model 单测和真实模型调试。
- 在模型调用或结构化输出失败时，不重试并显式降级到 `original_query`。
- 透传 LangChain callbacks，使现有 Langfuse callback 能观察 Graph 和模型调用。
- 提供离线契约测试、固定评测样例和显式执行的真实模型评测入口。

**Non-Goals**

- 不实现 Query Router、Retrieval Plan、Content Retriever、融合去重、Rerank 或 EvidencePackage。
- 不实现 RAG MCP server、HTTP API 或 Chat Graph 到 RAG 的调用。
- 不生成多查询、子问题、检索关键词列表、SQL、Cypher 或路由决策。
- 不让 RAG domain 按 `conversation_id` 读取 Chat 历史、checkpoint、Redis 或数据库。
- 不引入 Graph checkpointer、跨请求记忆、新模型供应商或新第三方依赖。
- 不把真实模型质量评测设为默认 pytest/CI 门禁。

## Decisions

### 1. RAG domain 使用独立、可序列化的契约

Query Rewrite 不复用 Chat Graph 的 `MessagesState` 或业务理解内部模型，避免 RAG domain 依赖调用方实现。输入模型包含：

- `original_query: str`：非空的当前问题。
- `conversation_context: list[ConversationContextMessage]`：调用方按时间顺序提供的有限原始上下文，可省略；不重复当前问题。
- `business_context: BusinessContext | None`：可选的意图和结构化实体，仅作为消歧参考。

模型输出只包含经过校验的 `standalone_query: str`。Graph state 在输入字段之外增加：

- `standalone_query`
- `rewrite_status`：`rewritten` 或 `fallback`
- `rewrite_failure_code`：有限枚举或空值
- `warnings`：可传递给未来 EvidencePackage 的非敏感警告

State 使用 `TypedDict` 表达 LangGraph 的可序列化共享状态；边界输入和模型结构化输出使用 Pydantic 校验。State 不保存 model、callback、settings 或其他运行时对象。

调用方负责上下文选择和 token 预算。Query Rewrite 不自动截取历史，也不访问任何外部记忆。

### 2. Prompt 执行“受约束的检索化改写”

Prompt 使用显式版本常量，并将系统规则、当前问题、会话上下文和业务上下文分区组织。核心规则是：

- 当前问题中的显式值高于历史和业务上下文。
- 只补全可以由所给信息唯一确定的省略或指代。
- 删除问候、礼貌用语和不改变信息需求的重复表达。
- 可以规范明确的错别字、别名和术语，但不能替换为其他实体。
- 必须保留实体、时间、数字、范围、否定、比较、归属和版本等硬约束。
- 只返回一条查询，不回答问题、不拆分子问题、不规划检索、不生成 SQL/Cypher。
- 已经适合检索的问题保持语义稳定，允许原样返回。

模型通过 `with_structured_output(QueryRewriteResult)` 调用。这样结果形状由代码校验，而不是从自由文本中手工提取。Prompt 不要求模型生成解释、置信度或中间推理。

### 3. 业务服务与 LangGraph node 分离

Query Rewrite 的核心实现放在 RAG domain 服务中，接收输入、注入的 Chat model 和当前 `RunnableConfig`，返回确定形状的状态更新。LangGraph node 只负责：

1. 从 state 组装服务输入；
2. 从 runtime context 取得 model，或使用开发期显式绑定的 model；
3. 调用服务并返回 state update。

这种分层允许 Prompt/降级逻辑脱离 Graph 做快速单测，同时保留真正的 node 和完整最小 Graph 测试。domain 模块导入时不会创建模型客户端或读取进程配置。

### 4. 失败只调用一次模型，并显式降级

每次 Query Rewrite 最多发起一次模型调用。普通模型异常或结构化输出无效时：

- 将 `standalone_query` 设置为原始问题；
- 将 `rewrite_status` 设置为 `fallback`；
- 写入有限、稳定且不包含供应商原始异常文本的 `rewrite_failure_code`；
- 追加一个非敏感 warning；
- 不重试，也不并行检索原始查询和部分改写结果。

实现只捕获普通 `Exception`，不捕获 `BaseException`，从而不把运行时取消或进程终止转换成成功降级。具体供应商异常不进入 Graph state，详细异常仍可由调用栈和 callback 观测。

### 5. 最小 Graph 复用现有运行时注入模式

新增独立的 RAG runtime context 和 Graph builder。builder 支持两种模式：

- 生产式模式：node 从 LangGraph runtime context 取得 model。
- 开发/测试绑定模式：builder 接收显式 model，便于 Studio 和单元测试运行。

Graph 只注册一个名为 `query_rewrite` 的业务节点，并连接：

```text
START -> query_rewrite -> END
```

Graph 编译时不提供 checkpointer。未来完整 RAG Graph 复用同一个 node 和 state 字段，而不是在本切片之外再实现一份 Rewrite。

### 6. 增加独立的 LangGraph Studio 开发入口

在 `backend/langgraph.json` 中增加一个 `rag_query_rewrite` graph，指向薄入口模块。入口复用现有 settings、模型工厂和可选 Langfuse resources，构造绑定模型的最小 Graph。

这个入口仅用于开发期手工输入和真实模型观察，不构成对外 RAG API，也不读取 Chat 会话。Langfuse 不可用时入口仍可运行。

### 7. Callback 由调用方注入并传递到模型调用

Query Rewrite 不直接依赖 Langfuse SDK，也不在 domain 内创建 trace。调用方通过 LangGraph `RunnableConfig.callbacks` 提供 Langfuse `CallbackHandler`，node 将同一个 config 传入结构化模型调用。

这样当前最小 Graph 可被直接观察；未来 RAG MCP/应用服务也可以创建更高层的 root trace，并让 Rewrite 自然成为其子运行。fallback 状态和 warning 保留在 Graph 输出中，方便调用方补充业务级属性。

### 8. 离线测试验证契约，真实模型评测验证质量

默认测试使用 fake/stub Chat model，覆盖：

- 输入及结构化输出校验；
- Prompt 分区和关键约束；
- 成功状态更新；
- 模型异常、空白/无效输出的单次调用与 fallback；
- callback config 透传；
- 最小 Graph 拓扑、无 checkpointer和可序列化输出。

仓库维护一组按高风险错误类型组织的数据驱动 Query Rewrite cases，重点覆盖多轮约束继承、当前输入覆盖历史、时间与数值范围、否定、比较、归属、标识符完整性和禁止臆造，并以少量口语去噪和已独立问题作为基线。每条样例同时保存人工参考的 `expected_standalone_query` 和 case-specific annotations；这些字段用于人工复核或作为 LLM Judge 的 rubric 上下文，不直接转换成关键词命中、token overlap、正则、编辑距离或参考答案 exact-match 分数。

代码 evaluator 只验证非空结构、状态枚举和 fallback 一致性等客观契约。真实模型评测由显式命令执行，调用生产 node/Graph 并逐条记录原问题、改写结果和契约状态；语义等价、上下文补全、约束保留、检索适用性和禁止臆造由人工或 LLM-as-a-Judge 评估。Judge 使用统一 rubric 输出分项分数与简短理由，并先与一组人工标注结果校准；校准完成前，Judge 分数不作为 CI、发布或 Prompt 自动选择门禁。

## Risks / Trade-offs

- **单次调用可能因瞬时错误直接降级。** 这是为控制延迟和调用成本做出的选择；warning 和状态使降级可观测，未来可基于线上数据再决定是否增加重试策略。
- **结构化输出仍不能保证语义正确。** Pydantic 只能保证形状，质量需要固定样例和真实模型评测持续验证。
- **LLM Judge 也不是绝对真值。** Judge 结果可能受模型、rubric 和顺序偏差影响，因此必须保留人工参考与理由，并先用人工标注样本做一致性校准。
- **调用方控制上下文可能导致不同入口行为不一致。** 本 change 明确 RAG 的输入契约，后续 Chat/MCP 接入应各自采用确定性的上下文窗口策略。
- **过度改写会损失约束，过度保守会降低召回。** Prompt 以约束保留优先，并通过分类样例观察平衡，不在 V1 引入第二次 LLM 判断。
- **开发入口会增加一个 Graph 配置项。** 它复用生产 node 和模型工厂，避免形成另一套实现；完成整体 RAG Graph 后可以再决定是否保留独立入口。

## Migration Plan

1. 新增 RAG Query Rewrite 契约、Prompt、服务、node 和最小 Graph，不修改现有 Chat Graph。
2. 增加离线测试和固定评测 cases。
3. 在 `backend/langgraph.json` 注册开发期 `rag_query_rewrite` Graph。
4. 使用显式真实模型评测命令观察结果；发现质量问题时优先调整版本化 Prompt 和 cases。
5. 后续完整 RAG Graph 直接复用该 node，并由 MCP/应用服务负责最外层 trace 和请求上下文。

本 change 完全是新增能力，不需要数据迁移或回滚脚本。回滚时移除独立 Graph 注册和新增 RAG 模块即可，不影响现有 Chat 流程。

## Open Questions

- 完整 RAG 接入时，会话上下文的具体 token 预算和消息选择算法由调用方规范确定，本 change 只定义输入边界。
- 真实模型评测采用哪个模型、可接受的延迟和约束保留阈值，需要在首轮样例运行后再确定。
