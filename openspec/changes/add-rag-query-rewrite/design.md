## Context

当前 `backend/app/domains/rag/` 尚未承载具体实现，而项目已经具备 LangChain、LangGraph、模型工厂和 Langfuse callback 基础设施。完整 RAG 链路仍在设计中，但 Query Rewrite 的输入边界、单查询输出、失败降级和与 Router 分离等决策已经稳定。

本 change 先实现完整 RAG Graph 的第一个纵向增量：调用方提供当前问题、裁剪后的原始会话上下文和可选业务上下文，RAG domain 使用装配期注入的 Chat model 生成一条 `standalone_query`。顶层 `RagState`、`build_rag_graph` 和 Studio 入口始终代表整条 RAG 管线；Query Rewrite 只是当前第一个业务节点，不构成独立子图。

## Goals / Non-Goals

**Goals**

- 定义不依赖 Chat domain、会话存储或外部服务的 Query Rewrite 输入输出契约。
- 实现“一对一、受约束的检索化改写”，并保留会改变检索结果的硬约束。
- 提供当前拓扑为 `START -> query_rewrite -> END` 的 RAG Graph，支持 fake model 单测和真实模型调试，并允许后续阶段直接追加。
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

模型输出只包含经过校验的 `standalone_query: str`。Graph state 在输入字段之外只增加 `standalone_query`。

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

Prompt 的完整查询要求和 few-shot 组织参考 know-engine `KnowEngineQueryTransformer`：先逐一执行信息需求识别、上下文补全、冲突覆盖、去噪与规范化，最后重组为独立完整查询；示例改为当前业务域的多轮补全、当前值覆盖、稳定查询和口语去噪场景，不复制其汽车领域内容或 transformer 外壳。

模型通过 `with_structured_output(QueryRewriteResult, method="json_mode")` 调用，随后继续使用 Pydantic 校验结果。首轮真实实验发现当前 OpenAI-compatible thinking model 在默认 `json_schema` 模式下会对单字符串 Schema 生成最短值，例如 `{"standalone_query":"查"}`；`function_calling` 又因 thinking mode 不支持 required tool choice 返回 400。`json_mode` 探针能生成完整查询，因此显式选择该模式，而不是退回自由文本手工解析。`QueryRewriteResult` 同时拒绝单个汉字或标点，异常仍沿用原查询 fallback。Prompt 不要求模型生成解释、置信度或中间推理。

### 3. Query Rewrite 先作为 Graph 阶段实现

本 change 只开发 RAG Graph，不为 Query Rewrite 暴露独立 service。阶段专属的契约、Prompt 和评测辅助代码放在 `graph/query_rewrite/`，模型调用、结构化输出校验和 fallback 放在 `graph/nodes/query_rewrite.py`。`query_rewrite_node(...)` 可通过显式 model 直接测试，其测试组织参考 Chat `business_understanding` 的方式，但不要求复制 Chat 的 runtime 注入结构。

这样既避免把未来完整 RAG 管线错误地抽象成单节点 service，也不会假设以后只有 Query Rewrite。等 Rewrite、Route、Retrieve、Fusion、Rerank 和 Evidence 等阶段形成完整管线后，再由 `domains/rag/services/` 暴露面向调用方的 RAG 管线服务。domain 模块导入时不会创建模型客户端或读取进程配置。

### 4. 失败只调用一次模型，并回退原始查询

每次 Query Rewrite 最多发起一次模型调用。普通模型异常或结构化输出无效时：

- 将 `standalone_query` 设置为原始问题；
- 不重试，也不并行检索原始查询和部分改写结果。

实现只捕获普通 `Exception`，不捕获 `BaseException`，从而不把运行时取消或进程终止转换成成功降级。当前阶段不在 Graph state 中记录 Rewrite 状态、失败码或 warning；如后续出现明确的诊断需求，再单独设计可观测契约。

### 5. 顶层 RAG Graph 在装配期绑定模型

新增管线级 `RagState` 和 `build_rag_graph(model=...)`。模型由应用或 Studio 装配层创建，并在 Graph 构建时绑定到 node。

当前 RAG 管线没有按请求切换模型或注入请求级服务依赖的需求，因此不定义 `RagRuntimeContext`，也不维护 runtime 与显式绑定两套执行模式。请求期变化的 callback 和 metadata 继续通过 `RunnableConfig` 传递。若未来出现明确的按请求选模需求，再基于该需求引入 runtime context。

当前增量只注册一个名为 `query_rewrite` 的业务节点，并连接：

```text
START -> query_rewrite -> END
```

Graph 编译时不提供 checkpointer。未来 Route、Retrieve、Fusion、Rerank 和 Evidence 阶段直接扩展同一个 builder 和 state；Query Rewrite 不作为子图，也不另建一套顶层 Graph。

### 6. 增加管线级 LangGraph Studio 开发入口

在 `backend/langgraph.json` 中增加一个 `rag` graph，指向薄入口模块。入口复用现有 settings、模型工厂和可选 Langfuse resources，构造当前已实现的 RAG Graph。

这个入口仅用于开发期手工输入和真实模型观察，不构成对外 RAG API，也不读取 Chat 会话。Langfuse 不可用时入口仍可运行。

### 7. Callback 由调用方注入并传递到模型调用

Query Rewrite 不直接依赖 Langfuse SDK，也不在 domain 内创建 trace。调用方通过 LangGraph `RunnableConfig.callbacks` 提供 Langfuse `CallbackHandler`，node 将同一个 config 传入结构化模型调用。

这样当前 RAG Graph 可被直接观察；未来 RAG MCP/应用服务也可以创建更高层的 root trace，并让 Rewrite 自然成为其子运行。

### 8. 离线测试验证契约，真实模型评测验证质量

默认测试使用 fake/stub Chat model，覆盖：

- 输入及结构化输出校验；
- Prompt 分区和关键约束；
- 成功状态更新；
- 模型异常、空白/无效输出的单次调用与 fallback；
- callback config 透传；
- RAG Graph 当前拓扑、无 checkpointer 和可序列化输出。

仓库维护一组按高风险错误类型组织的数据驱动 Query Rewrite cases，重点覆盖多轮约束继承、当前输入覆盖历史、时间与数值范围、否定、比较、归属、标识符完整性和禁止臆造，并以少量口语去噪和已独立问题作为基线。每条样例同时保存人工参考的 `expected_standalone_query` 和 case-specific annotations；这些字段用于人工复核或作为 LLM Judge 的 rubric 上下文，不直接转换成关键词命中、token overlap、正则、编辑距离或参考答案 exact-match 分数。

代码 evaluator 只验证输出非空且一次请求只有一条查询。真实模型评测由显式命令执行：将本地事实源中的 28 条样例以稳定 item ID 幂等同步到 `ke-engine/rag-query-rewrite-v1` Langfuse Dataset，再调用生产 RAG Graph 串行创建 Dataset Run。每个 item 保存原问题、上下文、人工参考查询和 case-specific 语义评审注释；Experiment 输出实际改写结果，并只写入 `output_contract` 客观分数。

语义等价、上下文补全、约束保留、检索适用性和禁止臆造由人工或 LLM-as-a-Judge 评估。Judge 使用统一 rubric 输出分项分数与简短理由，并先与一组人工标注结果校准；校准完成前，Judge 分数不作为 CI、发布或 Prompt 自动选择门禁。显式评测命令缺少模型或 Langfuse 配置、同步失败或无法创建 Dataset Run 时返回非零；默认 pytest 不调用网络。

## Risks / Trade-offs

- **单次调用可能因瞬时错误直接回退原查询。** 这是当前阶段为控制实现复杂度、延迟和调用成本做出的选择；本 change 不增加额外诊断字段。
- **结构化输出仍不能保证语义正确。** Pydantic 只能保证形状，质量需要固定样例和真实模型评测持续验证。
- **LLM Judge 也不是绝对真值。** Judge 结果可能受模型、rubric 和顺序偏差影响，因此必须保留人工参考与理由，并先用人工标注样本做一致性校准。
- **调用方控制上下文可能导致不同入口行为不一致。** 本 change 明确 RAG 的输入契约，后续 Chat/MCP 接入应各自采用确定性的上下文窗口策略。
- **过度改写会损失约束，过度保守会降低召回。** Prompt 以约束保留优先，并通过分类样例观察平衡，不在 V1 引入第二次 LLM 判断。
- **开发入口会增加一个 Graph 配置项。** 它复用生产 node 和模型工厂，避免形成另一套实现；完成整体 RAG Graph 后可以再决定是否保留独立入口。

## Migration Plan

1. 新增 RAG Query Rewrite 阶段契约、Prompt、node，并建立管线级 RAG Graph 的首个增量；不新增独立 Query Rewrite service，也不修改现有 Chat Graph。
2. 增加离线测试和固定评测 cases。
3. 在 `backend/langgraph.json` 注册开发期 `rag` Graph。
4. 使用显式真实模型评测命令观察结果；发现质量问题时优先调整版本化 Prompt 和 cases。
5. 后续完整 RAG Graph 直接复用该 node，并由 MCP/应用服务负责最外层 trace 和请求上下文。

本 change 完全是新增能力，不需要数据迁移或回滚脚本。回滚时移除 RAG Graph 注册和新增 RAG 模块即可，不影响现有 Chat 流程。

## Open Questions

- 完整 RAG 接入时，会话上下文的具体 token 预算和消息选择算法由调用方规范确定，本 change 只定义输入边界。
- 真实模型评测采用哪个模型、可接受的延迟和约束保留阈值，需要在首轮样例运行后再确定。
