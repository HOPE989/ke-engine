## Context

当前请求级 RAG Graph 仅包含 `query_rewrite`，输出一条 `standalone_query` 后结束。下一阶段需要把该查询转换为检索计划，但真实 Document、SQL 和 Graph Retriever 将在后续 change 中分别实现。

本 change 因此只建立 Router 的模型契约、Prompt、规范化逻辑、失败回退、Graph state 和离线评测，不执行任何检索。当前 RAG Graph 仍无 checkpointer，也不接入 Chat API。

## Goals / Non-Goals

**Goals:**

- 从 `DOCUMENT_HYBRID`、`SQL`、`GRAPH` 中选择一个或多个检索器。
- 只允许模型选择装配时显式提供的可路由能力。
- 将不可信的模型输出转换为确定、可序列化的 `RetrievalPlan`。
- 用简单、可预测的规则处理 Router 失败。
- 复用现有 RAG Graph、模型注入、callback 和真实模型评测方式。

**Non-Goals:**

- 不实现或模拟真实 Retriever。
- 不使用 `Command`、条件边或 `Send` 执行动态并行。
- 不定义检索结果、汇合、Rerank 或 EvidencePackage。
- 不实现 SQL/Cypher 生成及数据源权限。
- 不实现 Retriever 执行失败后的跨检索器降级。

## Decisions

### 1. 区分模型结果与可执行计划

模型结构化输出使用 `QueryRouteResult`：

```text
selected_retrievers: list[RetrieverKind]
routing_reason: str
```

节点在服务端校验后生成 `RetrievalPlan`：

```text
selected_retrievers: list[RetrieverKind]
routing_reason: str
decision_source: MODEL | FALLBACK
```

这样模型不能直接构造 Graph 控制流。第一版不加入 `confidence`、主检索器、每路查询或数据源参数，因为这些字段没有已定义的执行语义。

### 2. 使用固定三类顶层能力并支持多选

`RetrieverKind` 使用 `DOCUMENT_HYBRID`、`SQL`、`GRAPH`。Dense 与 BM25 属于 `DOCUMENT_HYBRID` 内部实现，不向 Router 暴露。

Prompt 要求选择回答问题所需的最小充分证据源集合，不因关键词或“保险”而默认全选。服务端对合法重复项去重，并按 `DOCUMENT_HYBRID`、`SQL`、`GRAPH` 的固定顺序规范化；顺序不表达优先级。

备选方案是只允许三选一，但无法表达“业务统计值及其统计口径”等天然需要异构证据的问题。

### 3. 能力集合由 Graph 装配时注入

`build_rag_graph` 接收非空的可路由能力集合并绑定到 Router 节点。Prompt 只列出该集合，节点再次验证模型选择是其非空子集。

本 change 的 Graph 在 Router 后结束，因此这些能力只用于计划生成和评测。后续接入真实 Retriever 时，Builder 必须从实际注册节点生成能力集合，并保证计划只能跳转到已注册节点。

备选方案是让模型始终看到全部能力，但这会允许它选择当前管线无法提供的能力。

### 4. Router 失败只做一次确定性回退

模型调用普通异常、超时、结构非法、空选择、未知能力或选择不可用能力时：

- 若 `DOCUMENT_HYBRID` 位于可路由集合中，生成只含该能力的 fallback 计划；
- 否则抛出稳定的 Router 不可用异常；
- 不重试，不执行全部能力；
- 运行时取消不转换为 fallback。

文档检索适合作为 Router 决策失败时的保守默认能力；SQL 和 Graph 不作为默认回退，以避免一次分类异常触发结构化数据访问。

### 5. 当前使用普通 state update 和静态边

`query_router` 返回普通 `QueryRouterUpdate`，Builder 使用静态边：

```text
START -> query_rewrite -> query_router -> END
```

本 change 没有 Retriever 节点，因此使用 `Command(goto=END)` 不会表达真实动态决策。后续注册 Retriever 时再把该节点调整为多目标 `Command(goto=[...])`。

### 6. 路由集合使用客观离线指标评测

仓库 fixture 作为 Router 样例的来源，覆盖三类单选、三种双选、三选、能力受限和 fallback。预期路由是离散集合，因此代码评测可以使用集合完全匹配、每类 precision/recall 和过度/遗漏路由率；`routing_reason` 只做结构检查，不做精确文本匹配。

真实模型评测继续使用显式命令和独立 Langfuse Dataset，不进入默认 pytest 或 CI gate。

## Risks / Trade-offs

- [Router-only Graph 生成尚不可执行的计划] → 当前入口仅用于 Studio、测试和评测；proposal 和输出契约明确本 change 不执行计划。
- [模型过度多选增加未来成本] → Prompt 强调最小充分集合，并在评测中单独统计过度路由。
- [固定能力描述随数据范围变化而过期] → 本 change 保持三类稳定边界，后续 Retriever change 再把描述接入实际能力目录。
- [文档 fallback 可能无法回答结构化问题] → fallback 仅保证产生保守计划，不宣称能够回答；不自动改选 SQL 或 Graph。

