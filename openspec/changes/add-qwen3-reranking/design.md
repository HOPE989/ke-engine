## Context

`DOCUMENT_HYBRID` 当前并发执行 Elasticsearch BM25 与 LangChain KNN。每个通道先把命中的检索子分段替换为完整父分段、按父分段去重，再以稳定 `chunkId` 执行应用层 RRF。默认每路候选上限是 10，但 RRF 当前直接按最终 `result_limit=5` 截断，因此尚不存在独立的精排候选池。

本 change 在父分段 RRF 后调用百炼 `qwen3-rerank`。运行环境已经通过 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL` 配置同一个百炼 Workspace；Base URL 的主机是 Workspace 专属主机，现有路径用于 OpenAI 兼容 Chat/Embedding，而 Qwen3 Rerank 使用同一主机下的 `/compatible-api/v1/reranks`。项目已经依赖异步 `httpx`，不需要 DashScope SDK 或新的 LangChain Community 依赖。

百炼接口为单个 Query/Document 设置 4,000 Token 上限。当前父分段通常显著小于该上限；本 change 接受极端超长父分段由服务端截断的风险，不引入父子分段往返替换、窗口聚合或重新切分。

## Goals / Non-Goals

**Goals:**

- 保持“子分段负责召回、父分段负责融合与精排”的现有检索语义。
- 固定实现 `BM25 Top10 + KNN Top10 → 父分段 RRF Top10 → Qwen3 Rerank → score >= 0.6 → Top5`。
- 一次请求提交同一批 RRF 父分段并取得全部候选的分数，避免拆批后比较不可比的分数。
- 复用现有百炼 Workspace Base URL 和 API Key，不复制凭证配置。
- 使用生产 Graph 的异步检索路径调用百炼，不阻塞事件循环。
- 让最终 Candidate 和检索诊断保留足以解释精排与过滤结果的分数、排名和请求标识。
- 维持现有 Hybrid 请求全有或全无的失败语义及取消传播。

**Non-Goals:**

- 不改父子分段生成、父分段替换时机、Elasticsearch mapping 或访问过滤。
- 不为超过百炼单条 Token 上限的父分段增加预检查、重新切分、滑窗评分或本地模型回退。
- 不接入本地 Qwen3/BGE、DashScope SDK、`ContextualCompressionRetriever` 或新的 LangChain 包。
- 不加入跨请求分数归一化、动态阈值、模型 A/B、端点探测、自动重试或熔断器。
- 不在百炼失败时回退到未经精排的 RRF 结果。
- 不改变 Chat API、EvidencePackage 或最终回答生成。

## Decisions

### 1. 父分段替换继续发生在每个召回通道和 RRF 之前

现有父分段替换把子分段的 `chunkId` 改为父分段 `chunkId`，同时保留 `matchedChunkId`，并在每个召回通道中稳定保留同一父分段的最高名次。RRF 因此从父分段视角融合 BM25 与 KNN；Qwen3 也必须接收 RRF 返回的完整父分段，而不是命中子分段。

候选顺序保持：

```text
BM25 Top10 ──→ parent expansion + per-channel dedup ──┐
                                                      ├─→ RRF Top10
KNN Top10  ──→ parent expansion + per-channel dedup ──┘
                                                           ↓
                                                qwen3-rerank(all 10)
                                                           ↓
                                                score >= 0.6 → Top5
```

备选方案是只按父 ID 融合、使用命中子分段精排。该方案会把语义判断重新退回子分段视角，无法评价父分段中跨子块的完整信息，因此不采用。

### 2. 复用现有检索预算并固定 Rerank 策略

`DocumentRetrievalOptions` 不增加字段。现有 `candidate_limit=10` 同时作为每路召回上限和 RRF 输出上限，现有 `result_limit=5` 作为 Rerank 最终结果上限，`rank_constant=60` 和请求 timeout 保持不变。模型 `qwen3-rerank`、Q&A 指令和最低分 `0.6` 使用模块级常量。

RRF 最多向 Rerank 交付 10 条父分段。若 RRF 为空，Retriever 直接返回空列表且不调用百炼；若不足 10 条，则按实际数量提交。

不新增 `rrf_result_limit`、`rerank_min_score`、模型名或指令配置。这些值已经作为本次需求确定，额外配置只会扩大实现和测试面。

### 3. 使用独立、可注入的百炼 Rerank 客户端

基础设施新增一个职责单一的异步 Qwen3 Rerank 客户端/评分器，由 `ElasticsearchHybridRetriever` 注入。它接受一个 query 和有序 `Document` 列表，返回与输入下标关联的 `relevance_score` 和请求 ID；Retriever 负责把分数映射回 Document、排序、过滤和生成诊断。

生产 Graph 使用共享的进程生命周期 `httpx.AsyncClient`。离线测试注入 fake 客户端或 `MockTransport`，默认测试不访问网络。本 change 只保证生产使用的 `ainvoke` 路径完成精排，不为未使用的同步入口增加一套 HTTP 实现。

不使用 `HuggingFaceCrossEncoder`，因为它加载本地权重；不使用 LangChain `CrossEncoderReranker`，因为百炼响应需要请求 ID、分数和阈值过滤，直接调用 HTTP 契约更简单。

### 4. 从现有 OpenAI 兼容配置派生 Rerank URL

启动装配继续读取：

```text
OPENAI_API_KEY
OPENAI_BASE_URL=https://<workspace-host>/compatible-mode/v1
```

Rerank 客户端解析并复用 `OPENAI_BASE_URL` 的 scheme、authority 和 Workspace host，构造：

```text
https://<workspace-host>/compatible-api/v1/reranks
```

Authorization 继续使用同一个 `OPENAI_API_KEY`。装配不得新增 `BAILIAN_API_KEY`、`DASHSCOPE_API_KEY` 或 `BAILIAN_WORKSPACE_ID`，也不得修改现有 Chat/Embedding 的 Base URL。Base URL 或 API Key 缺失时沿用现有启动校验，不新增端点可用性探测。

备选方案是复制一组 Rerank 专用环境变量。当前 Chat、Embedding 和 Rerank 明确位于同一 Workspace，这会制造重复的敏感配置和漂移风险，因此不采用。

### 5. 一次提交全部 RRF 候选并在本地执行阈值与 TopK

请求固定使用：

```json
{
  "model": "qwen3-rerank",
  "query": "<standalone_query>",
  "documents": ["<parent-1>", "..."],
  "top_n": "<documents length>",
  "instruct": "Given a web search query, retrieve relevant passages that answer the query."
}
```

客户端按百炼公开响应读取 `results[].index` 与 `results[].relevance_score`。缺失字段、越界下标或不能解析的响应直接作为调用失败向上传播，不增加响应修复或部分结果兜底。Retriever 按以下稳定规则重排：

1. `relevance_score` 降序；
2. 分数相同时按原 RRF rank 升序；
3. 仍相同时按稳定 `chunkId` 升序。

之后过滤 `score < 0.6` 的候选并截取前 5 条。阈值判断使用包含边界，即 `score == 0.6` 保留。全部被过滤时返回空列表，Graph node 将其投影为正常 `EMPTY`。

把 API `top_n` 直接设成 5 虽然响应更小，但会丢失后五条的分数和过滤诊断，因此不采用。把 10 条拆成多个请求会得到不能可靠横向比较的请求内相对分数，也不采用。

### 6. 最终 Candidate 与诊断保留 Rerank 可解释性

通过 Rerank 的 `Document.metadata` 增加内部 `rerankScore`，Graph node 将其投影为 `DocumentCandidate.rerank_score`。该字段只来自成功的百炼响应，不推导、不归一化，也不使用 RRF score 冒充。

`RetrievalDiagnostics.stages` 保留现有 `RECALL`、`PARENT_EXPANSION`、`RRF`，并新增 `RERANK`：

- 各阶段候选的最多 200 字符 `textPreview`；
- 模型名；
- 请求 ID；
- Rerank 调用耗时；
- 每个候选的原 RRF rank、Rerank rank、`chunkId`、score 和是否通过阈值；
- 阈值与最终结果上限。

诊断不得保存 API Key、Authorization header、完整 Query、不受限的父分段正文、原始响应或原始异常文本。各阶段保留最多 200 字符的正文预览用于检索链路排查；最终总 `duration_ms` 包含 Rerank 调用。

### 7. 百炼是 Hybrid 请求的必需依赖

HTTP timeout、非成功状态或响应解析错误直接作为普通依赖失败，由现有 `document_hybrid` node 转换为 `FAILED` 且不包含候选。系统不重试、不探测备用端点，也不返回 RRF Top5 fallback。

RRF 为空或所有合法 Rerank 分数低于 `0.6` 是正常 `EMPTY`，与依赖失败区分。异步取消继续向上传播，不转换成 `FAILED`，底层异步 HTTP await 接收取消。

## Risks / Trade-offs

- [固定 `0.6` 阈值可能在真实语料中过严或过松] → 先按已确定策略实现并记录 Top10 分数，后续需要时直接调整模块常量。
- [百炼网络延迟增加检索 P95] → 只提交 RRF Top10、复用长连接、一次请求获取全部分数，并把调用耗时单独纳入诊断。
- [百炼故障导致原本可用的 RRF 结果变为 FAILED] → 明确保持全有或全无语义，依赖监控通过 request ID、状态与耗时定位；若后续需要 fallback，应作为显式策略变更。
- [父分段偶发超过 4,000 Token 后被服务端截断] → 接受该低概率边界；本 change 不改变父分段语义或加入复杂窗口逻辑。
- [由 OpenAI Base URL 派生专用路径与百炼 URL 结构耦合] → 集中在一个经过单元测试的 URL 构造函数中，校验 scheme/host，并避免散落字符串替换。
- [提供方响应结构变化导致调用失败] → 依赖公开的 `index` 与 `relevance_score` 契约，解析失败直接形成 `FAILED`，不猜测或修复响应。
- [诊断泄露检索正文或凭证] → 诊断采用字段白名单，正文只保留最多 200 字符的 `textPreview`，并记录 ID、rank、score、计数、时长和请求标识。

## Migration Plan

1. 部署前确认现有 `OPENAI_BASE_URL` 仍指向百炼 Workspace 专属 `/compatible-mode/v1`，`OPENAI_API_KEY` 对该 Workspace 有效；不增加新环境变量。
2. 部署包含 Rerank 客户端、检索选项、Retriever 接入、Candidate/诊断和离线测试的版本。
3. 先在开发环境验证 `10 + 10 → 10 → 0.6 → 5`、正常空结果和脱敏诊断，再进入生产环境。
4. 观察百炼调用耗时、失败率、过滤后结果数和分数分布；阈值调整通过后续代码变更完成。
5. 回滚时恢复未接入 Rerank 的 Retriever 版本；现有百炼/OpenAI 配置、Elasticsearch 数据、父子分段和对外 API 均无需迁移或恢复。

## Open Questions

无。初始候选预算、阈值、最终 TopK、父分段时机、配置复用和失败语义均已确定。
