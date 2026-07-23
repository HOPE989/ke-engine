# RAG 查询链路与 MCP 服务设计草稿

> 状态：讨论中
> 最后更新：2026-07-23
> 用途：持续记录 RAG 查询服务、检索编排和 MCP 暴露方式的阶段性结论。
> 说明：本文是 `docs/my-specs` 下的探索草稿，不是已进入实施阶段的 OpenSpec change。标记为“已确认”的内容表示当前讨论基线；标记为“待讨论”的内容仍可能调整。

## 1. 讨论目标

ke-engine 已经具备文档上传、转换、切分、Embedding 和 Elasticsearch 向量存储能力，但尚未形成面向在线问答的完整召回链路。

本轮希望设计一个独立部署的 RAG 服务，统一提供企业知识证据获取能力，并通过 MCP 暴露给当前 Chat Service、后续 Agent 项目和其他项目使用。

这里的“企业知识”不限于非结构化文档，还包括：

- Elasticsearch 中的文档与片段；
- 关系型数据库中的结构化业务数据；
- 后续可能接入的图数据库知识。

RAG 服务当前只负责获取证据，不负责生成最终业务回答。

## 2. 当前工程基础

### 2.1 已有入库能力

当前 `document` domain 已经负责：

- 文档上传与对象存储；
- 文档格式转换；
- 文档切分；
- Embedding；
- Elasticsearch 向量写入；
- 文档和 segment 生命周期管理。

Elasticsearch 向量文档已有的主要元数据包括：

- `docId`
- `chunkId`
- `fileName`
- `url`
- `accessibleBy`
- `parentChunkId`
- `langchain`
- `images`

### 2.2 当前 Chat 能力

当前 `chat` domain 已经使用 LangGraph，并通过 runtime context 注入模型等运行依赖。生产 Chat Graph 已接入 Langfuse `CallbackHandler`，能够自动记录 Graph、节点和模型调用。

RAG 服务后续将复用这种“Graph 只保存业务状态，客户端对象通过 runtime context 注入”的模式。

## 3. 已确认的服务边界

### 3.1 独立部署

项目采用单仓多服务形态。RAG 将作为独立服务部署，而不是作为 Chat Service 内部模块运行。

```text
Chat Service / Agent / 其他项目
                │
                │ MCP
                ▼
          RAG MCP Service
                │
                ├── Elasticsearch
                ├── 关系型数据库
                ├── Embedding / Rerank 模型
                └── 后续可能接入 Neo4j
```

所有跨服务消费者通过 MCP 使用 RAG 能力，不直接调用 RAG domain 内部 Python 类。

### 3.2 MCP 只是服务适配层

RAG 服务使用官方 MCP SDK，不手动实现 MCP、JSON-RPC、Tool Discovery 或 Streamable HTTP。

但 MCP SDK 只存在于服务适配层：

```text
官方 MCP SDK
    ↓
services/rag_mcp
    ↓
domains/rag
    ↓
Retrieval Graph / Content Retrievers
```

`domains/rag` 不导入 MCP SDK。它只提供普通 Python 应用接口和领域模型。这样可以避免检索逻辑与 MCP 版本、传输协议和 Tool 注册方式绑定。

### 3.3 Document 与 RAG 的职责

```text
document domain
    └── 负责知识入库和索引写入

rag domain
    └── 负责在线查询、召回、融合、重排和证据封装
```

RAG 查询链路不修改文档和索引。

### 3.4 结构化数据属于 RAG

此前讨论中曾沿用旧文档结论，把 SQL Tool 放在 Chat Service 管理。该结论已被本轮讨论覆盖。

当前边界是：

> 结构化业务数据也是企业知识库的一部分，Text2SQL/SQL 检索能力由 RAG MCP Service 管理。

RAG MCP Service 的能力范围因此包括：

- 非结构化文档检索；
- 结构化 SQL 检索；
- 后续可能增加的图知识检索。

当前确认采用同一 RAG 进程、两个 MCP Endpoint：

- 标准 Endpoint 暴露完整召回管线 Tool；
- 专家 Endpoint 暴露文档、SQL 和 Graph 原子 Tool；
- 两者复用同一组 domain services 和运行资源。

## 4. 已确认的框架选择

### 4.1 LangChain 提供能力组件

LangChain 用于提供或接入：

- Document 和 Retriever 抽象；
- Elasticsearch 检索；
- Embedding；
- LLM；
- Reranker；
- 其他可复用的检索组件。

### 4.2 LangGraph 负责编排

LangGraph 用于表达：

- 显式阶段状态；
- 条件路由；
- 多路并行召回；
- 汇合；
- 降级；
- 后续可能增加的循环补检索。

不机械地把每个函数都包装成节点。只有满足以下至少一项的阶段才应成为节点：

- 需要独立观察耗时和结果；
- 可能独立失败或降级；
- 存在并行或条件路由；
- 将来可能循环重试；
- 具有清晰的阶段输入输出。

文本清洗、字段转换、分数计算等局部纯函数保留在节点内部。

### 4.3 Graph 不使用 Checkpointer

RAG 当前是单次 MCP 请求内完成的无会话检索服务：

- 一次调用对应一次 Graph invocation；
- 不维护对话生命周期；
- 不需要中断和恢复；
- 不使用 LangGraph Checkpointer。

如果未来出现长时间检索、人工确认或跨请求恢复需求，再单独评估持久化执行。

## 5. 已确认的 Langfuse 观测方式

Langfuse `CallbackHandler` 是 Graph 观测的主要接入方式：

```text
CallbackHandler
├── 自动记录 Graph 调用
├── 自动记录节点执行路径
├── 自动记录 LangChain Retriever
├── 自动记录 LLM / Embedding / Reranker
├── 自动记录耗时、Token、模型和异常
└── 自动形成 observation 层级
```

不为每个 LangGraph 节点重复手工创建 observation。

手工增强只负责 CallbackHandler 无法自动表达的内容：

- MCP 跨服务 Trace Context；
- 调用方、用户、环境和知识库范围；
- 各路候选数量；
- Fusion 去重数量；
- 最终证据数量；

分布式 Trace 的当前倾向是：

- 上游通过 MCP `_meta` 传递 W3C Trace Context 时，RAG 继续该 Trace；
- 没有上游 Trace Context 时，RAG 创建独立的 `rag-retrieval` Trace；
- `EvidencePackage.trace_id` 返回实际 Trace ID；
- Langfuse 初始化、上报或关闭失败必须 fail-open，不得改变检索结果。

## 6. know-engine 对照结论

已对照本地 `LLMentor/know-engine` 的实际代码。旧系统基于 LangChain4j `DefaultRetrievalAugmentor`，主要流程是：

```text
Intent Recognition
    ↓
Query Transformer
    ↓
Query Router
    ↓
Content Retriever
    ↓
Content Aggregator
    ↓
Content Injector
    ↓
LLM Answer
```

### 6.1 旧系统 Query Transformer

- 基于当前问题和历史对话做一次同步 LLM 改写；
- Prompt 包含五类策略：简洁化、抽象概念化、错别字纠正、车型信息标准化和上下文补全；
- 五类策略不是分别生成五条查询，而是要求模型“逐一使用，最终给出一个统一的改写结果”；
- 当前实现只返回一个改写查询，原始查询不继续参与召回；
- 代码中曾考虑返回“改写查询 + 原始查询”，但该返回语句已被注释；部分单元测试仍按两条查询断言，已经与生产代码不一致；
- 历史上下文来自最近 10 条 USER/ASSISTANT 消息；当前轮刚保存的 USER 和空 ASSISTANT 会被排除，当前问题通过独立的 `query` 变量传入；
- 不生成上下文摘要，也不按 Token Budget 裁剪；
- 没有结构化输出、改写类型、查询目的或质量置信度；
- LLM 调用是同步的；异步虚拟线程只负责把改写文本回写数据库，并没有消除 Query Rewrite 本身的模型延迟；
- 当前实现没有对空响应或语义漂移做显式校验和原查询降级。

### 6.2 旧系统 Query Router

Router 使用固定 Prompt 做单标签分类，只能三选一：

- `knowledge_base`
- `relational_db`
- `graph_db`

它不是“知识库必查，再按需追加 SQL 或 Graph”，而是互斥路由：

```text
knowledge_base
    OR
relational_db
    OR
graph_db
```

其中：

- `knowledge_base` 固定并行执行 KNN 和 FullText；
- `relational_db` 只执行 Text2SQL，空结果或异常时回退 KNN；
- `graph_db` 只执行 Text2Cypher，空结果或异常时回退 KNN；
- `confidence` 虽然由 LLM 输出，但没有参与低置信度多路召回；
- Router 解析失败时返回空 Retriever 列表。

### 6.3 旧系统聚合

- KNN 和 FullText 结果使用 RRF 融合；
- 非结构化结果使用本地 BGE Reranker；
- SQL 和 Cypher 成功结果标记为 `skipRerank`，直接透传；
- 最终内容由 `ContentInjector` 注入回答模型。

### 6.4 对新系统的启示

新系统不直接复制旧系统的单选路由和失败语义，重点保留：

- 显式 Query Rewrite；
- 显式 Query Router；
- 并行召回；
- Hybrid Retrieval；
- RRF；
- Rerank；
- 结构化与非结构化证据统一返回。

需要改进：

- 保留原始查询；
- Router 支持选择一个或多个知识获取能力；
- 路由失败不能静默返回空结果；
- 不把 SQL、文档和图结果强行放入同一排名分数；
- 返回结构化 EvidencePackage，而不是直接注入最终回答模型。

## 7. 当前确认的总体召回链路

```text
Original Query
    ↓
Query Rewrite
    ↓
Query Router
    ↓
Retrieval Plan
    ↓
并行执行选中的 Content Retriever
    ├── Hybrid Document Retriever
    ├── SQL Content Retriever
    └── Graph Content Retriever（后续）
    ↓
Document Rerank
    ↓
异构证据合并
    ↓
Build EvidencePackage
    ↓
通过 RAG MCP 返回
```

### 7.1 Content Retriever 的抽象层级

当前确认不把 Dense 和 BM25 暴露为 Router 直接选择的顶层 Content Retriever。

```text
ContentRetriever
├── HybridDocumentRetriever
│   ├── Dense Retrieval Channel
│   ├── BM25 Retrieval Channel
│   └── RRF + Deduplicate
├── SqlContentRetriever
└── GraphContentRetriever
```

含义是：

- Content Retriever 表示一种知识获取能力；
- Dense 和 BM25 是 Hybrid Document Retriever 内部的算法通道；
- Query Router 在 `document_hybrid`、`sql`、`graph` 之间选择一个或多个；
- Router 不负责关闭 Dense 或 BM25。

### 7.2 Hybrid Document Retriever

Hybrid Document Retriever 内部固定包含：

```text
Dense
  ┐
  ├── RRF → 按 chunk_id 去重 → Document Candidates
BM25
  ┘
```

后续如果评测证明有必要，可以增加内部 profile：

- `balanced`
- `semantic_biased`
- `lexical_biased`

Router 最多选择 profile，不直接操作底层 Retriever。

### 7.3 多能力组合示例

| 用户问题 | 候选 Retrieval Plan |
|---|---|
| 装车作业有哪些要求？ | `document_hybrid` |
| 本月各客户发运量是多少？ | `sql` |
| 本月发运量是多少，相关统计口径是什么？ | `sql + document_hybrid` |
| A 站与 B 站有什么运输关系？ | `graph` |
| Router 失败 | `document_hybrid` |

以上是当前方向示例，不代表 Router Prompt 和降级规则已经最终确定。

## 8. 异构证据聚合原则

不同知识类型不共享同一套排名语义。

### 8.1 文档结果

- Dense 和 BM25 使用 RRF；
- 按 `chunk_id` 去重；
- 多个改写查询产生的文档候选需要进一步融合；
- 融合后的文档候选进入 Rerank；
- 保留原始召回分数、排名、Fusion 分数和 Rerank 分数。

### 8.2 SQL 结果

- 按业务主键或结果集指纹去重；
- 不参与文档 RRF；
- 不使用文档 CrossEncoder/BGE Rerank；
- 需要独立的结构化结果校验、口径和来源描述。

### 8.3 Graph 结果

- 按节点、边或路径标识去重；
- 不参与文档 RRF；
- 需要保留图查询、节点、关系和路径来源。

### 8.4 统一证据

不同结果最终统一封装，而不是强制归一成一个不可解释的分数：

```text
EvidenceItem
├── evidence_type
│   ├── document
│   ├── structured_data
│   └── graph
├── content
├── source
├── metadata
├── retrieval_query
├── retriever_id
└── scores
```

## 9. EvidencePackage 当前方向

RAG MCP 返回结构化证据，不返回最终自然语言回答：

```text
EvidencePackage
├── evidence_items
│   ├── document_id
│   ├── chunk_id
│   ├── evidence_type
│   ├── content
│   ├── source
│   ├── metadata
│   ├── retrieval_query
│   ├── retriever_id
│   ├── retrieval_score
│   ├── fusion_score
│   └── rerank_score
├── citations
├── applied_filters
├── retrieval_diagnostics
└── trace_id
```

具体字段仍需随着 Query Rewrite、Router 和异构证据设计继续收敛。

## 10. 建议的代码分层

```text
backend/app/
├── entrypoints/
│   └── rag_mcp.py
├── services/
│   └── rag_mcp/
│       ├── server.py
│       ├── deps.py
│       └── schemas.py
├── domains/
│   └── rag/
│       ├── graph/
│       │   ├── builder.py
│       │   ├── state.py
│       │   └── nodes/
│       ├── retrievers/
│       ├── services/
│       └── shared/
└── infrastructure/
    ├── elasticsearch_retrieval.py
    ├── sql_retrieval.py
    ├── reranker.py
    └── langfuse.py
```

该目录只是当前设计方向，尚未进入代码实施。

## 11. Query Rewrite：下一步讨论草稿

### 11.1 已确认的适用入口

通用 Query Rewrite 只属于标准 Endpoint 的完整召回管线：

```text
retrieve_evidence
    ↓
Query Rewrite
    ↓
Route → Retrieve → EvidencePackage
```

专家 Endpoint 的三个原子 Tool 不执行通用 Query Rewrite：

- `search_documents` 信任调用方提供的精确文档检索子问题，只做文档检索必需的规范化；
- `query_structured_data` 信任调用方提供的结构化查询意图，内部执行 Text2SQL；
- `query_graph` 信任调用方提供的图查询意图，内部执行 Text2Cypher。

这样可以避免具备规划能力的调用方 Agent 已经拆解问题后，RAG 再次抽象或扩写查询，造成双重规划和限定条件丢失。

### 11.2 已确认职责

Query Rewrite 的目标是把用户原始问题转换为一个可独立理解、适合检索的 `standalone_query`，同时不得丢失原始问题中的关键事实和限制条件。

第一版职责包括：

- 删除不影响语义的口语噪声；
- 纠正明显错别字和术语；
- 把依赖上下文的问题补全为独立问题；
- 标准化领域术语、实体名称和时间表达；
- 将多个相关限定条件保留在同一个完整查询中；
- 在 Graph State 中保留原始查询用于审计、离线评测和 Rewrite 失败降级，但正常情况下不把它作为第二条检索查询。

第一版不做多查询扩展或问题拆解。即使原问题包含多个信息需求，Query Rewrite 也只输出一个 `standalone_query`，整个请求只运行一条查询管线。

#### 11.2.1 已确认的改写强度

第一版采用“受约束的检索化改写”，而不是纯粹复述成完整疑问句，也不是把具体问题过度抽象成通用关键词：

```text
上下文补全
  + 表达压缩
  + 术语规范化
  - 语义泛化
  - 条件丢失
  = retrieval-oriented standalone_query
```

其中：

- `standalone` 表示查询脱离历史对话后仍可独立理解；
- `retrieval-oriented` 表示删除口语、礼貌用语、重复表达和无效修饰，并转换为简洁的检索意图表达；
- `constrained` 表示必须保留实体、时间、数值、范围、否定、比较、归属等硬约束；
- 不允许凭空补充事实、改变用户意图、扩大或缩小问题范围；
- 已经独立且适合检索的输入允许基本原样返回。

示例：

```text
历史实体：2024 款比亚迪汉 EV
原问题：它最近每次踩刹车都会响，应该怎么办？

不采用的纯补全：
2024 款比亚迪汉 EV 最近每次踩刹车时都会出现异响，应该如何排查和处理？

不采用的过度抽象：
车辆刹车异响故障排查

采用的 standalone_query：
2024 款比亚迪汉 EV 刹车异响原因、排查与处理方法
```

### 11.3 已确认的上下文来源

标准 `retrieve_evidence` 调用由调用方提供当前问题和可选的、已裁剪原始上下文：

```text
RetrieveEvidenceRequest
├── query
├── conversation_context
└── business_context
    ├── intent
    └── entities
```

职责边界是：

- Chat Service 从 `ChatState.messages` 中截取上下文；
- 其他 Agent 从自己的工作记忆中截取上下文；
- 非对话型调用可以不传 `conversation_context`；
- RAG 不接受 `conversation_id` 后自行访问调用方的会话数据库；
- Business Understanding 继续负责业务边界、意图、实体和澄清，不增加自然语言 `rag_context_summary` 或 `rewritten_query`；
- Business Understanding 的结构化结果可以作为 `business_context` 提示；
- Query Rewrite 使用原始上下文完成指代消解、语义补全和检索改写。

第一版不增加独立的 LLM 上下文摘要。调用方使用确定性窗口策略：

1. 当前问题始终单独传递；
2. 从当前问题之前开始，按 Token Budget 从后向前选取最近消息；
3. 尽量保留完整问答轮次，不从中间截断单条消息；
4. 不传系统 Prompt、内部 Tool 输出、密钥或无关运行数据；
5. Token Budget 的具体数值通过模型上下文和评测确定，当前不提前固定。

know-engine 的对照实现采用最近 10 条 USER/ASSISTANT 原始消息和当前问题进行改写，不生成上下文摘要。新系统保留“原始消息窗口”思路，但将固定消息条数改进为 Token Budget。

### 11.4 已确认的第一版输出

```text
QueryRewriteResult
└── standalone_query
```

`original_query` 已经存在于请求和 Graph State 中，不在 Query Rewrite 输出中重复返回。Router 只接收一次 `standalone_query`。

“只走一条查询管线”不等于“只允许一个 Retriever”：Router 仍可以为这一条查询选择一个或多个 Content Retriever，Hybrid Document Retriever 内部也仍然可以并行执行 Dense 和 BM25。这里限制的是查询级 fan-out，而不是检索源级并行。

### 11.5 DeerFlow 对照：一对多更接近研究规划

已核对本地 `deer-flow-1`。其中没有发现一个独立的、在召回前一次性输出多条检索查询的 Query Rewrite 节点。容易被理解为“问题一对多改写”的能力实际分为三层：

1. `Prompt Enhancer` 把一个宽泛提示增强为一个更具体、结构化的提示，输出仍是一条 `enhanced_prompt`；
2. `Planner` 把主研究主题扩展并拆成多个 `Step`，每个 Step 有 `title`、`description`、`step_type` 和 `need_search`，这些 Step 表达多个垂直研究方向；
3. `Researcher` 按顺序执行每个 research Step，并在 ReAct 工具调用过程中自行生成一个或多个搜索关键词。Planner 不预先输出最终的搜索词列表。

其实际控制流更接近：

```text
原始问题
  → Coordinator 澄清/补全研究主题
  → Planner 拆成多个垂直研究 Step
  → 每个 Step 交给 Researcher
  → Researcher 自主调用 Web Search / Local RAG
```

因此 DeerFlow 的一对多设计主要解决“复杂研究任务如何获得全面覆盖”，而不是低延迟 RAG 中“如何扩大单次召回命中率”。它对未来版本有两点参考价值：

- 如果未来引入多查询扩展，可以借用结构化、带目的的一对多表示，而不是只返回字符串数组；
- 不应直接照搬开放式研究规划。标准 `retrieve_evidence` 需要限制变体数量、保持查询彼此正交，并避免把 Query Rewrite 扩张成多步 Agent 计划。

第一版明确不采用 DeerFlow 式拆解，仅将其保留为未来演进参考。

### 11.6 know-engine 与 DeerFlow 的组合启示

两者解决的是 Query Rewrite 的不同子问题：

```text
know-engine：原问题 → 上下文化、纠错、规范化 → 一条独立完整查询
DeerFlow：    研究主题 → 按信息需求拆解       → 多个垂直研究方向
```

第一版借鉴 know-engine 的一对一方向，但不照搬其可能丢失具体条件的过度抽象：

```text
original_query
  → contextualize + normalize
  → standalone_query
  → Router
  → 单条查询管线
```

`expand_or_decompose` 不进入第一版范围，避免查询数量放大后触发多条 Router、Retriever、Fusion 和 Rerank 执行链。未来只有在单查询召回评测证明存在明确缺口时，才重新评估多查询扩展。

### 11.7 已确认的模型调用边界

Query Rewrite 和 Query Router 保持为两个独立阶段，各自调用模型，不为了减少调用次数而合并：

```text
Query Rewrite LLM
  → standalone_query
  → Query Router LLM
  → selected retrievers
```

Retriever 不增加一层通用的 LLM 查询改写：

- `HybridDocumentRetriever` 直接使用 `standalone_query` 执行 Dense 和 BM25；分词、大小写、同义词等由 Elasticsearch Analyzer 或纯代码处理；
- `SqlContentRetriever` 直接使用 `standalone_query` 执行 Text2SQL，不在 Text2SQL 前增加 SQL-specific Rewrite；
- `GraphContentRetriever` 直接使用 `standalone_query` 执行 Text2Cypher，不在 Text2Cypher 前增加 Graph-specific Rewrite。

因此文档路径包含 Rewrite 和 Router 两次模型调用；SQL 或 Graph 路径会再包含其检索机制所必需的 Text2SQL 或 Text2Cypher 调用。

### 11.8 已确认的失败语义

第一版为 Query Rewrite 提供可观测降级：

```text
Rewrite 成功
  → standalone_query = rewritten query

Rewrite 失败
  → standalone_query = original_query
  → 继续 Router 和召回
```

模型调用异常、超时、空输出或输出不满足协议时，不中断整个 RAG 请求，而是使用用户原始问题继续检索。当前阶段只保证回退行为，不在 Graph State 或 EvidencePackage 中增加 Rewrite 状态、失败码或 warning；不重试 Rewrite，避免进一步增加前置延迟。

对照实现中：

- know-engine 的 `QueryTransformer` 没有空输出校验或原查询回退，模型异常会向上抛出；
- DeerFlow 1.x 没有与当前链路等价的 standalone Query Rewrite；其独立 `Prompt Enhancer` 会在异常时返回原提示，而 Planner 对 JSON 做修复和格式校验。这些属于 DeerFlow 自身的交互与规划容错，不作为当前 Query Rewrite 的设计依据。

### 11.9 已确认的 Query Rewrite 评测策略

Query Rewrite 是生成式任务，可能存在多种同样正确的表达。因此第一版不使用以下
规则判断语义质量：

- 与参考改写逐字相等；
- 固定关键词包含关系；
- Token overlap、正则、编辑距离；
- BLEU、ROUGE 等面向表面文本相似度的指标。

代码评测只负责客观、确定性的输出契约：

- `standalone_query` 是符合协议的非空字符串；
- 一次请求只产生一条查询。

语义质量由人工评审或 LLM-as-a-Judge 负责，评价维度暂定为：

- `semantic_fidelity`：与原始信息需求语义等价；
- `context_resolution`：正确补全可唯一确定的上下文，并以当前问题覆盖冲突历史；
- `constraint_preservation`：保留实体、标识符、时间、数值范围、否定、比较、归属和版本等约束；
- `retrieval_readiness`：查询独立、简洁，适合 Router 和 Retriever；
- `non_invention`：不引入输入中不存在的事实或过滤条件；
- `single_query_compliance`：只输出一条查询，不回答问题，也不生成 SQL、Cypher 或执行计划。

实验数据已先在本地以
`backend/tests/fixtures/query_rewrite_cases.json` 起草。当前共 28 条、13 个
易错或典型类别。每条 case 包含真实输入、人工参考改写以及 case-specific
annotations。参考答案和 annotations 是人工复核或 Judge 的上下文，不进入生产
Rewrite task，也不作为代码关键词匹配规则。

当前尚未配置 LLM-as-a-Judge，不阻塞 Query Rewrite 开发。Langfuse 分阶段使用：

```text
阶段 1：Dataset Experiment
  本地 fixture 同步为 Langfuse Dataset
  → 运行真实 Query Rewrite
  → 生成可比较的 Dataset Run

阶段 2：人工基线
  Experiment Compare / Annotation Queue
  → PASS / PARTIAL / FAIL
  → 错误类型 + 评论 + 可选人工修订结果

阶段 3：Judge 校准
  配置 LLM Connection 和自定义 Judge
  → Judge 只读取 input、实际 output、expected_output
  → 与人工标签比较一致性并分析分歧

阶段 4：自动化
  Judge 经校准后，才考虑用于 Prompt 选择、回归门禁或生产监测
```

人工评审第一版使用一个总质量标签即可：

- `PASS`：可直接用于检索；
- `PARTIAL`：基本可用，但存在轻微约束损失、冗余或表达问题；
- `FAIL`：语义漂移、错误继承上下文、丢失关键约束、凭空补充或不满足单查询边界。

同时记录可多选的错误类型：

- `context_resolution_error`
- `constraint_loss`
- `semantic_drift`
- `unsupported_invention`
- `not_standalone`
- `over_rewrite`

待配置 Judge 后，初始 Judge 也先输出 `PASS / PARTIAL / FAIL` 和简短理由，不直接
设置 CI 阈值。Judge 必须先在一组由人工按同一 rubric 标注的代表性输出上校准；
生产 Rewrite task 绝不能读取 Dataset 的 `expected_output`。可行时，Judge 模型
与被测 Rewrite 模型使用不同模型，以降低同源偏差。

Langfuse Hosted Dataset 作为正式实验载体：通过 SDK 对 Hosted Dataset 运行
Experiment 时会生成可在 UI 比较的 Dataset Run；只在本地列表上运行则只产生
traces 和 scores，不形成 Dataset Run。开发阶段优先使用 Experiment，生产阶段
再把已校准 evaluator 挂到目标 observation。

### 11.10 需要继续讨论的问题

1. 哪些字段和中间结果进入 Langfuse，哪些内容需要脱敏？
2. 人工基线由谁评审，以及首轮抽取多少条真实模型输出？
3. Judge 的模型、Prompt、标签一致性阈值和正式启用条件是什么？

## 12. 其他未决问题

### 12.1 MCP Tool 与内部 Retriever 的粒度

需要区分两个概念：

- `ContentRetriever` 是 RAG domain 内部的知识获取组件；
- MCP Tool 是面向外部调用方的稳定能力协议。

二者不必一一对应。当前存在三种候选方案。

#### 方案 A：只暴露原子检索 Tool

```text
Agent
├── search_documents
├── query_structured_data
└── query_graph
```

调用方 Agent 自己决定调用顺序、是否并行、是否补检索以及如何组合结果。

优点：

- Agent 对检索计划拥有最大控制权；
- 适合需要多轮调查和逐步取证的复杂任务；
- 每个 Tool 的权限、参数和成本边界清晰。

风险：

- Query Rewrite、路由、结果融合和证据预算容易散落到每个调用方；
- 普通服务也必须具备 Agent 编排能力；
- 不同调用方可能形成不同质量标准和失败语义；
- MCP 往返次数、模型调用次数和整体延迟更高。

#### 方案 B：只暴露完整召回管线

```text
Caller
    ↓
retrieve_evidence
    ↓
Rewrite → Route → Retrieve → Fuse → Rerank → EvidencePackage
```

优点：

- 调用方只需要表达问题和约束；
- 检索质量、ACL、降级、诊断和评测口径集中治理；
- 非 Agent 项目也能稳定复用；
- 一次 MCP 调用可以完成多路并行召回。

风险：

- 对高级 Agent 而言内部决策较黑盒；
- Agent 难以明确指定只查询某个知识来源；
- 复杂任务可能在调用方规划和 RAG 内部规划之间产生重复判断。

#### 方案 C：分层能力

默认提供完整管线 Tool：

```text
retrieve_evidence
```

同时保留按权限或服务配置开放的专家 Tool：

```text
search_documents
query_structured_data
query_graph
```

完整管线与专家 Tool 复用同一组 domain services，不允许完整管线通过 MCP 回调本服务自己的专家 Tool。

该分层方案已确认。标准调用方使用完整管线，具备检索规划能力的 Agent 使用专家 Tool。

需要进一步确认：

- 当前 Chat Service 和后续 Agent 项目分别需要多大检索控制权；
- 调用方能否明确区分“文档证据”“结构化事实”和“图关系”；
- 专家 Tool 是否需要单独的授权、限流和审计；
- 同时暴露统一 Tool 和专家 Tool 是否会造成模型选 Tool 歧义。

#### Tool 集合的候选控制方式

MCP Client 通过 `tools/list` 获取服务端返回的 Tool 定义。不同调用方拿到不同集合，可以通过三种方式实现。

1. 调用方过滤：
   - MCP Server 返回全部 Tool；
   - 调用方在绑定给模型前按 allowlist 过滤；
   - 只能控制模型可见性，不能作为安全授权。
2. 同一 Endpoint 动态过滤：
   - MCP Server 根据访问令牌中的 client、role 或 scope 动态响应 `tools/list`；
   - `tools/call` 必须重复执行同一授权判断；
   - 灵活，但通常需要低层 MCP handler 或自定义策略层。
3. 同一进程挂载不同 MCP Endpoint：
   - 标准 Endpoint 只注册 `retrieve_evidence`；
   - 专家 Endpoint 只注册三个原子 Tool；
   - 两个 Endpoint 复用同一组 lifespan 资源和 domain services；
   - Tool Discovery 清晰，适合当前 FastMCP 静态注册方式。

当前已确认采用第三种：

```text
RAG Service
├── /mcp/rag
│   └── retrieve_evidence
└── /mcp/rag-expert
    ├── search_documents
    ├── query_structured_data
    └── query_graph
```

无论采用哪种可见性策略，服务端都必须在每次 `tools/call` 时校验调用方 scope。Tool 未出现在 `tools/list` 中不等于调用方无法绕过模型直接按名称发起调用。

### 12.2 其他问题

- Query Router 的结构化输出协议；
- Router 多选、置信度和默认降级规则；
- SQL 查询生成、只读限制、超时、行数限制和审计；
- Graph Retriever 是否进入第一版；
- 异构证据合并后的数量预算；
- Reranker 模型、阈值和失败降级；
- ACL、租户和用户上下文如何通过 MCP 安全传递；
- MCP 错误模型；
- 端到端、节点级和检索质量测试策略；
- 正式 OpenSpec change 的首版范围。

## 13. 当前非目标

当前讨论不包含：

- RAG 服务生成最终业务回答；
- 修改现有文档入库链路；
- 开放式 Agent Runtime；
- Web Search；
- 长任务和人工中断恢复；
- 立即实现代码。

## 14. 本轮交接检查点

当前开发状态：

- 分支：`feat/rag-query-rewrite`
- OpenSpec change：`add-rag-query-rewrite`
- OpenSpec 规划产物：proposal、design、delta spec、tasks 均已完成并通过 strict validation；
- 实现任务：尚未开始，当前为 0/68；
- 已提交基线：`dc0491f docs(rag): define query rewrite design and TDD plan`

当前工作区还有一组属于本 change、尚未提交的评测设计改动：

- 本设计草稿的 Query Rewrite 评测策略；
- `design.md`、delta spec、`tasks.md` 中的语义评测边界；
- `backend/tests/fixtures/query_rewrite_cases.json` 的 28 条实验 dataset 草稿。

接手者不要把 dataset 中的参考查询或 annotations 改造成确定性关键词 scorer。
它们只服务于人工评审和未来经校准的 LLM Judge。代码 scorer 只检查输出协议、
状态和 fallback 一致性。

建议下一步：

1. 先评审并提交上述尚未提交的文档与 dataset 改动；
2. 退出探索阶段，使用 `openspec-apply-change` 按 `tasks.md` 的 TDD 顺序实现；
3. 完成 Query Rewrite node 后先运行 28 条真实模型 Experiment；
4. 当前没有 LLM-as-a-Judge 配置，因此先建立人工 `PASS / PARTIAL / FAIL` 基线，
   不设置语义质量 CI gate；
5. Query Rewrite 验证稳定后，再继续讨论 Query Router 的多选协议和降级规则。
