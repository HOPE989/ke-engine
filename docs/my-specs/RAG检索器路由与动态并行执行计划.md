# RAG 检索器路由与动态并行执行计划

> 状态：实施前探索草稿，尚未进入正式 OpenSpec change
>
> 创建时间：2026-07-26
>
> 适用范围：`ke-engine` 的标准 RAG 证据召回管线
>
> 上游基线：`docs/my-specs/RAG查询链路与MCP服务.md`
>
> 对照实现：`C:/dev/workspace/LLMentor/know-engine`

## 1. 文档目的

当前 `ke-engine` 已完成 RAG Query Rewrite，现有管线拓扑为：

```text
START → query_rewrite → END
```

下一阶段需要增加 Query Router，并逐步形成能够按请求动态选择一个或多个
Content Retriever、并行执行、汇合结果、隔离部分失败并返回结构化证据的完整
RAG 查询管线。

本文用于：

- 固化 Router、Retriever、动态并行和结果汇合之间的职责边界；
- 记录对 `LLMentor/know-engine` 实际实现的取舍；
- 将目标架构拆分为可独立评测、可独立验收的 OpenSpec change；
- 避免在 Router change 中提前创建没有真实实现的空壳 Retriever；
- 为下一步创建 `add-rag-query-router` proposal 提供实施基线。

本文是探索草稿，不等同于正式需求、设计或任务清单。每个阶段开始实现前，仍需
创建独立 OpenSpec change，并以该 change 的 proposal、design、spec 和 tasks
作为最终实施依据。

## 2. 当前工程事实

### 2.1 已实现能力

`backend/app/domains/rag/` 当前只实现 Query Rewrite：

- 接收 `original_query`、可选会话上下文和可选业务上下文；
- 输出一条 `standalone_query`；
- 模型调用或结构化输出失败时回退原问题；
- Graph 不使用 checkpointer；
- Graph state 只保存可序列化的请求数据和业务结果；
- Studio 入口可以使用真实模型观察当前管线。

### 2.2 尚未实现能力

当前代码中尚不存在：

- Query Router；
- Retrieval Plan；
- 在线 Hybrid Document Retrieval；
- Text2SQL 查询运行时；
- Neo4j/Text2Cypher 查询运行时；
- Retriever 动态并行编排；
- Retrieval Outcome 汇合；
- Document Rerank；
- EvidencePackage；
- RAG MCP Endpoint。

现有 Elasticsearch 基础设施是文档入库和向量存储适配器，不能视为已实现在线
Hybrid Retriever。现有数据查询表结构和 Spreadsheet ingestion 也不能视为已完成
Text2SQL 查询安全边界。

## 3. `know-engine` 对照结论

### 3.1 实际控制流

`know-engine` 的实际流程是：

```text
Query Transformer
        ↓
Query Router（LLM 单选 strategy）
        │
        ├── knowledge_base
        │      ├── KNN Retriever ─────┐
        │      └── FullText Retriever ├── 并行
        │                             │
        ├── relational_db             │
        │      └── Text2SQL           │
        │          └── 失败/空 → KNN  │
        │                             │
        └── graph_db                  │
               └── Text2Cypher        │
                   └── 失败/空 → KNN  │
                                      ↓
                      Hybrid Content Aggregator
                      ├── SQL/Cypher：直接透传
                      └── 文档：RRF → BGE Rerank
                                      ↓
                              注入最终回答模型
```

Router 返回 `Collection<ContentRetriever>`。本地实际使用的 LangChain4j
`DefaultRetrievalAugmentor` 在 Retriever 数量大于 1 时，通过
`CompletableFuture.supplyAsync` 并行调用，并用 `allOf(...).join()` 等待全部结果。

因此它采用的核心模式是：

```text
Router
  → 返回运行时 Retriever 集合
  → RetrievalAugmentor 并行执行
  → Aggregator 汇合
```

这与 `ke-engine` 的目标模式在思想上相同：

```text
Router
  → 生成 Retrieval Plan
  → LangGraph 动态选择节点并行执行
  → Collect/Fusion 节点汇合
```

### 3.2 值得保留的设计

- Router 决定本次执行哪些知识获取能力，而不是由调用方硬编码；
- 文档路径固定组合 KNN 和全文检索；
- 多个 Retriever 可以并行执行并在后续统一汇合；
- SQL/Cypher 结果不参与文档 RRF 和文档 Rerank；
- Query Rewrite、Route、Retrieve、Aggregate 是独立阶段。

### 3.3 不直接复制的设计

`ke-engine` 不复制以下行为：

- Router 只能在 `knowledge_base / relational_db / graph_db` 中三选一；
- `confidence` 被模型输出但不参与任何执行决策；
- Router 失败时执行全部 Retriever；
- 使用具体实现类的 `instanceof` 判断 Retriever 类型；
- SQL/Graph 失败后在 Retriever 内部静默切换到 KNN；
- SQL、Cypher 和文档结果过早压成同一种通用 `Content`；
- 一个并行 Retriever 抛出异常时导致整个并行批次失败；
- SQL/Graph 使用硬编码用户 ID 或未经授权校验的自然语言上下文；
- 每次请求重新组装全部 Retriever 和管线对象；
- 手写自由文本 JSON 示例，再通过修复和解析获得 Router 结果。

需要特别注意：`know-engine` 当前 Router 代码在 JSON 解析失败或 strategy 非法时
返回全部 Retriever；README 中“失败返回空结果”的描述已经落后于实际代码。

## 4. 目标架构

### 4.1 顶层拓扑

```text
Original Query
      ↓
Query Rewrite
      ↓
Query Router
      ↓
Retrieval Plan
      │
      ├── document_hybrid ──┐
      ├── sql ──────────────┼── Collect Retrieval Outcomes
      └── graph ────────────┘
                                  ↓
                         Document Rerank（按需）
                                  ↓
                         Build EvidencePackage
                                  ↓
                              RAG MCP
```

Router 可以选择一个或多个顶层 Retriever：

```text
document_hybrid
sql
graph
```

Dense 和 BM25 不是 Router 直接选择的顶层能力，而是
`document_hybrid` 内部固定执行的算法通道：

```text
document_hybrid
├── Dense Retrieval
├── BM25 Retrieval
└── RRF → 按 chunk_id 去重
```

### 4.2 LangGraph 路由方式

三个顶层 Retriever 是固定、异构并且需要独立观察的业务节点，因此第一选择不是
把所有检索任务发给一个通用 worker，也不是为动态性强行使用 `Send`。

当 Query Router 同时更新 `retrieval_plan` 并决定下一跳时，目标形态是：

```python
Command(
    update={"retrieval_plan": plan},
    goto=["document_hybrid", "sql"],
)
```

`goto` 中出现的节点在下一 LangGraph superstep 并行执行。

只有在未来出现以下需求时才考虑 `Send`：

- 同一种 Retriever 需要按运行时数量未知的多个数据源实例 fan-out；
- 同一个 worker 需要接收多个不同的局部输入；
- 每个动态任务需要独立 timeout 或任务级参数；
- Retriever 从固定三类扩展为运行时注册的任意数量插件。

### 4.3 Router 输出协议

第一版建议使用以下概念模型：

```text
QueryRouteResult
├── routes: list[RetrieverKind]       # 1..3 个唯一值
└── routing_reason: str               # 简短、可评测，不是执行依据

RetrieverKind
├── document_hybrid
├── sql
└── graph
```

模型输出在进入 Graph state 前转换为规范化的 `RetrievalPlan`：

```text
RetrievalPlan
├── routes
├── routing_reason
└── decision_source
    ├── model
    └── fallback
```

第一版不加入：

- `confidence`：没有经过校准，也没有明确阈值行为；
- 每路独立查询字符串：避免 Router 提前承担问题拆解和多查询扩展；
- Dense/BM25 开关：属于 Hybrid Retriever 内部策略；
- SQL、Cypher 或数据源连接参数：属于对应 Retriever 的输入与安全边界；
- 调用方可直接覆盖的 route override：避免绕过标准管线治理。

### 4.4 可用能力与授权能力

Router 只能选择当前请求实际允许执行的能力：

```text
effective_retrievers
    = deployed_retrievers
    ∩ caller_authorized_retrievers
    ∩ request_applicable_retrievers
```

- `deployed_retrievers`：服务装配时真实可用的实现；
- `caller_authorized_retrievers`：调用方身份和 scope 允许使用的能力；
- `request_applicable_retrievers`：本次知识库、数据源或租户配置允许的能力。

Router Prompt 只描述 `effective_retrievers`，结构化输出仍要在服务端校验为其子集。
如果交集为空，应在进入模型调用或 Graph 执行前返回明确配置/授权错误。

Router 不是授权机制。每个 Retriever 节点仍需再次验证资源范围、租户、ACL 和
只读约束，不能因为 Router 选择了某个节点就默认获得访问权限。

### 4.5 并行结果协议

并行节点不能共同覆盖一个没有 reducer 的普通 state 字段。目标状态采用按
Retriever ID 合并的结果映射：

```text
retrieval_outcomes
├── document_hybrid → RetrievalOutcome
├── sql             → RetrievalOutcome
└── graph           → RetrievalOutcome
```

概念上的 `RetrievalOutcome`：

```text
RetrievalOutcome
├── retriever_id
├── status
│   ├── success
│   ├── empty
│   ├── failed
│   └── timed_out
├── evidence
├── diagnostics
│   ├── duration_ms
│   ├── candidate_count
│   ├── result_count
│   └── sanitized_error_code
└── fallback_from（可选）
```

Graph state 使用确定性的 reducer 按 `retriever_id` 合并 outcome。执行结果和最终
证据顺序不能依赖并行分支的完成顺序。

### 4.6 汇合方式

当三个顶层 Retriever 都是单个 Graph 节点时，可以分别连接到同一个 collect
节点。被选中的节点在同一个 superstep 并行完成后，collect 节点读取合并后的
`retrieval_outcomes`。

不能使用固定的：

```python
graph.add_edge(
    ["document_hybrid", "sql", "graph"],
    "collect_results",
)
```

这种写法表达“等待三个节点全部完成”，而动态路由中未选中的节点不会执行。

如果未来某条分支变成多级分支，例如：

```text
document_hybrid → document_rerank
sql
graph
```

则需要使用 deferred collector 或显式 branch-complete 机制，避免 collect 在较短
分支完成后提前运行。第一版优先保持三个顶层 Retriever 各自为单节点，并在统一
collect 之后按需执行 Document Rerank。

### 4.7 失败与降级语义

#### Router 失败

以下情况统一回退 `document_hybrid`：

- 模型调用普通异常；
- 模型调用超时；
- 空输出或无法解析；
- routes 为空、重复、超出数量或包含非法值；
- routes 包含当前不可用或未授权能力。

不执行“失败后全量检索”，避免一次 Router 错误触发 SQL、Graph 和多个模型调用。
不重试 Router，第一版优先控制前置延迟。

#### Retriever 失败

每个 Retriever 节点捕获其可预期的外部依赖异常和节点级超时，并返回
`failed/timed_out` outcome。不得捕获取消、进程终止或其他 `BaseException`。

一个 Retriever 失败不能丢弃其他成功分支的证据。

#### Retriever fallback

SQL 或 Graph 节点不得在内部静默调用 Document Retriever。需要 fallback 时，
由后续显式策略节点决定：

```text
selected sql
    ↓
sql failed or empty
    ↓
fallback policy
    ├── document_hybrid 尚未执行 → 显式补检索
    └── document_hybrid 已执行   → 复用已有结果
```

fallback 后仍要保留：

- 原计划选择了哪个 Retriever；
- 原 Retriever 的失败/空结果状态；
- fallback 实际执行了哪个 Retriever；
- 最终证据的真实来源。

第一版 Router change 不实现 Retriever fallback 循环，只定义该目标语义。

### 4.8 异构证据处理

不同 Retriever 的结果不共享同一排名语义：

- 文档候选：Dense/BM25 RRF、按 `chunk_id` 去重、Document Rerank；
- SQL 结果：结构化校验、结果集限制、来源和口径描述，不参与文档 RRF；
- Graph 结果：节点/边/路径去重，保留 Cypher 和图来源，不参与文档 RRF；
- 最终按类型统一封装，而不是强行归一为一个不可解释的全局分数。

## 5. 实施依赖图

```text
Query Router 协议、Prompt、评测
                │
                ▼
Hybrid Document Retrieval
                │
                ├──────────────┐
                ▼              ▼
       SQL Retrieval      Graph Retrieval
                └──────┬───────┘
                       ▼
          异构结果汇合与 EvidencePackage
                       ▼
                  RAG MCP Service
```

实施采用纵向增量：

- 每个 change 都有可运行的 Graph 拓扑；
- 每个 change 都有离线确定性测试；
- 真实模型或真实基础设施验证显式执行，不进入默认离线测试；
- 不在一个 change 中同时承担 Router、Hybrid、SQL、Neo4j 和 MCP。

## 6. Change 1：`add-rag-query-router`

### 6.1 目标

实现可独立评测的多选 Query Router，并把当前 RAG Graph 扩展为：

```text
START → query_rewrite → query_router → END
```

Router 只生成和保存 `RetrievalPlan`，本 change 不执行 Retriever。

为了与未来动态路由保持一致，Router 节点可以返回：

```text
Command(update={"retrieval_plan": ...}, goto=END)
```

后续接入 Retriever 时只扩展 `goto` 目标，不需要重新定义 Router 输出协议。

### 6.2 任务拆分

#### Task 1：定义 Router 输入输出契约

**内容**

- 定义 `RetrieverKind`；
- 定义 `QueryRouteResult` 和规范化 `RetrievalPlan`；
- 校验 routes 非空、唯一、数量不超过 3；
- 校验 routes 是有效能力集合的子集；
- `RagState` 增加可选 `retrieval_plan`。

**验收标准**

- routes 支持单选和多选；
- 重复、空列表、未知类型和未授权类型被拒绝；
- 状态中不保存 model、client、settings 或 provider 异常对象。

**预计范围**：S～M。

#### Task 2：实现版本化 Router Prompt

**内容**

- 描述 Document、SQL、Graph 各自适用边界；
- 明确允许选择一个或多个能力；
- 为组合问题提供少量示例；
- 明确只从有效能力集合中选择；
- 禁止回答问题、生成 SQL/Cypher 或拆出多条查询；
- 不要求 confidence 和长推理过程。

**验收标准**

- Prompt 不出现“可以多选”与“一次只能单选”的冲突；
- Prompt 明确结构化输出格式；
- 当前 `standalone_query` 与能力目录分区传入；
- Prompt 版本可在评测记录中识别。

**预计范围**：S。

#### Task 3：实现 Router node 与确定性降级

**内容**

- 使用装配注入的 Chat model；
- 调用结构化输出；
- 二次执行 Pydantic 校验和规范化；
- 普通异常或无效输出回退 `document_hybrid`；
- 不捕获取消；
- 透传 RunnableConfig callbacks；
- 返回包含 plan 更新并跳转 `END` 的 Command。

**验收标准**

- 每次 Router 最多调用模型一次；
- 成功计划原样进入 state；
- 失败计划明确标记 `decision_source=fallback`；
- 不保存原始 provider 错误文本；
- Langfuse callback 可观察 Router 和模型调用。

**预计范围**：M。

#### Task 4：扩展 RAG Graph 与 Studio

**内容**

- 注册 `query_router` 节点；
- 修改 `query_rewrite` 后继为 `query_router`；
- Router 负责当前阶段到 `END` 的动态控制；
- Studio 继续加载同一个顶层 RAG Graph；
- Graph 仍不使用 checkpointer。

**验收标准**

- 拓扑精确为 `START → query_rewrite → query_router → END`；
- Query Rewrite fallback 后仍会进入 Router；
- state 和最终输出可序列化；
- 不新增第二套 Router-only 顶层 Graph。

**预计范围**：S。

#### Task 5：建立 Router 离线测试与评测集

**内容**

- Fake model 契约测试；
- 单路样例：Document、SQL、Graph；
- 多路样例：Document+SQL、Document+Graph、SQL+Graph；
- 边界样例：模糊问题、混合信息需求、不可用能力；
- 模型异常、非法结构、空 routes、重复 routes 的降级测试；
- 单独的真实模型 Dataset/Experiment 入口；
- 人工评审 Router 的合理性，不用关键词命中代替语义评测。

**验收标准**

- 默认 pytest 不访问网络；
- 评测样例包含单选、多选和 fallback；
- 代码 evaluator 只验证客观协议；
- 路由质量由人工或经校准的 Judge 评估；
- 未校准 Judge 不作为 CI gate。

**预计范围**：M。

### 6.3 Checkpoint

- Router delta spec 已覆盖输入、输出、多选、降级、观测和评测；
- Router 聚焦测试通过；
- RAG Query Rewrite 现有回归全部通过；
- 全量非集成测试通过；
- 使用真实模型人工检查代表性单路与多路样例；
- OpenSpec strict validation 通过；
- 人工评审确认后再归档 change。

### 6.4 Non-Goals

- 不实现任何真实 Retriever；
- 不连接 Elasticsearch 在线检索；
- 不生成或执行 SQL/Cypher；
- 不实现并行 outcome reducer；
- 不实现 EvidencePackage 或 MCP；
- 不修改 Chat Service。

## 7. Change 2：`add-rag-hybrid-document-retrieval`

### 7.1 目标

实现第一个真实 Retriever，并建立后续 SQL/Graph 可复用的动态执行与结果汇合基础。

目标拓扑：

```text
query_rewrite
      ↓
query_router
      ↓
document_hybrid
      ↓
collect_retrieval_outcomes
      ↓
document_rerank
      ↓
build_document_evidence
      ↓
END
```

当前已部署能力只有 `document_hybrid` 时，Router Prompt 只暴露该能力。测试可以用
fake Retriever 验证多目标 Command 和 reducer，但生产 Graph 不注册无实现节点。

### 7.2 任务方向

- 定义 `ContentRetriever` 领域协议和 Document 候选模型；
- 实现 Dense Retrieval；
- 实现 BM25 Retrieval；
- 并发执行 Dense 和 BM25；
- RRF、按 `chunk_id` 去重；
- 实现文档过滤、ACL 和知识库范围；
- 定义 `RetrievalOutcome` 和按 retriever ID 合并的 reducer；
- Router 从 `goto=END` 调整为 `goto=选中的已注册节点`；
- 实现 collect、Document Rerank 和 Document Evidence；
- 建立 ES 集成测试与离线 fake 测试；
- 增加候选数、去重数、耗时和失败状态观测。

### 7.3 Checkpoint

- Document-only 真实纵向链路可运行；
- Dense/BM25 并行且结果确定性融合；
- ACL 和知识库过滤不能被 Router 绕过；
- 单通道失败的降级策略有明确测试；
- Graph 不注册 SQL/Graph 空节点；
- 全量非集成测试和显式 ES 集成测试通过。

## 8. Change 3：`add-rag-sql-retrieval`

### 8.1 目标

增加安全、可审计的 SQL Content Retriever，并首次在生产 Graph 中支持两个异构
Retriever 动态并行：

```text
query_router
      ├── document_hybrid ──┐
      └── sql ──────────────┼── collect_retrieval_outcomes
```

### 8.2 前置安全要求

- 数据源和 schema 必须来自服务端配置，不由模型或外部调用方自由指定；
- 只允许只读查询；
- 限制可访问表、字段和租户范围；
- 使用真实调用方身份，不硬编码用户 ID；
- 设置 statement timeout、最大行数和结果大小；
- 记录生成 SQL、执行数据源、耗时、行数和拒绝原因；
- 明确禁止 DDL、DML、多语句、注释逃逸和危险函数；
- Router 选择 SQL 不构成 SQL 授权。

### 8.3 任务方向

- 定义 SQL Retriever 输入和结构化证据模型；
- 建立 schema/catalog 获取边界；
- 实现 Text2SQL 结构化输出；
- 实现 SQL AST/协议校验和只读执行；
- 实现结果集预算和序列化；
- 注册 `sql` node；
- 验证 `sql` 单路和 `sql + document_hybrid` 并行；
- SQL 失败返回 outcome，不在节点内部静默调用 Document Retriever；
- 增加安全、超时、权限、空结果和数据库异常测试。

### 8.4 Checkpoint

- SQL 纵向链路通过真实数据库集成测试；
- 只读和权限测试覆盖拒绝场景；
- SQL 与 Document 并行时一个分支失败不丢弃另一个分支结果；
- SQL 证据不进入文档 RRF/Rerank；
- fallback 来源可追踪。

## 9. Change 4：`add-rag-graph-retrieval`

### 9.1 目标

引入 Neo4j 生命周期和 Graph Content Retriever，完成三路动态路由目标：

```text
query_router
      ├── document_hybrid ──┐
      ├── sql ──────────────┼── collect_retrieval_outcomes
      └── graph ────────────┘
```

### 9.2 前置安全要求

- Neo4j driver 由服务生命周期管理；
- 只允许只读 Cypher；
- 限制数据库、label、relationship、property 和 procedure；
- 禁止写入、危险 procedure 和无限路径扩展；
- 设置查询超时、记录数和路径深度预算；
- 保留实际 Cypher、节点、关系和路径来源；
- 使用真实调用方身份和资源范围。

### 9.3 任务方向

- 定义 Graph Retriever 输入和图证据模型；
- 实现 Text2Cypher 结构化输出；
- 实现 Cypher 校验和只读执行；
- 注册 `graph` node；
- 验证 Graph 单路和全部多路组合；
- 实现图结果去重与预算；
- Graph 失败返回 outcome，不在节点内部静默调用 Document Retriever；
- 增加权限、超时、空结果、路径预算和 Neo4j 异常测试。

### 9.4 Checkpoint

- 三种 Retriever 可按计划选择任意非空子集；
- 三路并行汇合结果确定；
- Graph 证据不进入文档 RRF/Rerank；
- 一个或两个来源失败时仍可保留其余成功证据；
- Neo4j 生命周期和关闭顺序经过测试。

## 10. Change 5：异构证据与显式 fallback

建议在三类 Retriever 契约稳定后单独收敛以下能力：

- Retrieval Outcome 汇总；
- 文档 Rerank；
- SQL、Graph 和 Document 的独立预算；
- 显式 fallback policy；
- 证据冲突与空结果语义；
- EvidenceItem 和 EvidencePackage；
- citations、applied filters 和 retrieval diagnostics；
- trace ID 与跨 MCP trace context；
- 标准 `retrieve_evidence` 应用服务接口；
- 后续 RAG MCP Endpoint。

如果前三个 Retriever change 已经自然形成稳定 EvidencePackage，本 change 可以缩小
或取消；不得为了遵守本文分期而机械增加没有独立价值的 change。

## 11. 测试与评测矩阵

| 层级 | 默认执行 | 主要验证 |
|---|---|---|
| 模型/契约单测 | 是 | Pydantic、Prompt、fallback、state update |
| Graph 拓扑单测 | 是 | Command、动态目标、并行 reducer、汇合 |
| Fake Retriever 单测 | 是 | success/empty/failed/timed_out 组合 |
| Router 数据集评测 | 显式 | 单路、多路、误路由、过度路由 |
| Elasticsearch 集成测试 | 显式 | Dense、BM25、RRF、ACL |
| SQL 集成与安全测试 | 显式 | 只读、权限、超时、行数和审计 |
| Neo4j 集成与安全测试 | 显式 | Cypher 只读、范围、路径预算 |
| 端到端 RAG 实验 | 显式 | 召回质量、延迟、成本、部分失败 |

质量指标至少分开观察：

- Router 单路准确性；
- Router 多路完整性；
- Router 过度路由率；
- 文档 Recall@K、去重率和 Rerank 改善；
- SQL/Cypher 生成有效率；
- SQL/Cypher 执行成功率；
- 空结果率；
- 部分失败保留成功证据的比例；
- P50/P95 端到端延迟；
- 每次请求模型调用数和外部数据源调用数。

## 12. 主要风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| Router 过度多选 | 延迟、成本和数据源压力上升 | Prompt 边界、最大 3 路、评测过度路由率 |
| Router 漏选 | 证据不完整 | 多路组合样例、人工评审、按意图补充数据集 |
| Router 失败全量执行 | 触发昂贵或未授权能力 | 固定回退 `document_hybrid` |
| 并行写同一 state key | InvalidUpdate 或结果覆盖 | 使用按 retriever ID 合并的 reducer |
| 一个分支异常拖垮全部 | 丢失其他成功证据 | 预期异常转换为结构化 outcome |
| fallback 隐藏真实来源 | 诊断和引用不可解释 | 使用显式 fallback 节点和 `fallback_from` |
| SQL/Cypher 越权或写入 | 高安全风险 | 双层授权、只读校验、范围、超时和审计 |
| 文档/SQL/Graph 强行统一分数 | 排名不可解释 | 分类型预算和证据字段 |
| 空壳 Retriever 污染生产拓扑 | 行为虚假、测试误导 | 只有真实实现完成后才注册节点 |
| 分支长度变化导致提前汇合 | 结果缺失 | deferred collector 或 branch-complete 机制 |
| 多次 fallback 重复执行文档检索 | 浪费资源、结果重复 | fallback policy 检查已有 outcome |

## 13. 当前明确非目标

- RAG 直接生成最终自然语言业务回答；
- Router 生成多条查询或研究计划；
- Router 直接生成 SQL/Cypher；
- 调用方提交 route override；
- Router 替代权限校验；
- 在 Router change 中一次实现全部 Retriever；
- 使用 LangGraph checkpointer；
- 为无实现能力创建 no-op 节点；
- 将未校准 LLM Judge 作为 CI 或发布门禁；
- 修改现有文档入库链路。

## 14. 待正式 change 确认的问题

1. `routing_reason` 是否进入最终 EvidencePackage，还是只进入 Langfuse observation？
2. `effective_retrievers` 的部署能力和请求授权分别由 builder、runtime context 还是
   应用服务输入承载？
3. Router 失败回退 `document_hybrid` 时，如果调用方无文档权限，应返回明确错误
   还是使用另一个服务端配置的默认能力？
4. 多路问题第一版是否始终把同一条 `standalone_query` 传给各 Retriever，还是允许
   后续增加受约束的 per-route purpose？
5. SQL/Graph 单路失败且没有文档证据时，标准 Endpoint 是返回空 EvidencePackage、
   部分失败状态，还是执行显式 Document fallback？
6. Document Rerank 是统一 collect 后执行，还是未来作为 Document 分支的独立阶段？
7. Neo4j 是否有明确首版业务数据、schema 和权限模型；如果没有，Change 4 应继续
   延后，但 Router 协议可保留 `graph` 类型。

## 15. 下一步

当前没有活跃 OpenSpec change。本文评审通过后，下一步是创建：

```text
add-rag-query-router
```

该 proposal 的首版范围应严格限定为：

- 多选 Router 协议；
- 版本化 Prompt；
- 结构化输出校验；
- `document_hybrid` 默认降级；
- `query_rewrite → query_router → END` Graph 增量；
- 离线测试和显式真实模型评测。

真实 Retriever、动态并行执行、异构结果汇合和 MCP 均属于后续 change，不应在
Router proposal 中隐式扩大范围。
