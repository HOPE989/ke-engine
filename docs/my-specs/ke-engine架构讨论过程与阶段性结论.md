# ke-engine 架构讨论过程与阶段性结论

> 记录日期：2026-07-20 至 2026-07-21
> 文档性质：讨论纪要、思路复盘和阶段性结论，不是正式技术规格，也不是实施计划。  
> 记录目的：保留本轮关于 LLMentor know-engine、DeerFlow 1.x、ke-engine 和后续 Agent 项目之间关系的完整思考过程，避免以后只记得结论，却忘记结论产生的背景、争议和边界。
>
> 阅读提示：第 1～15 节记录第一轮围绕 AUTO/DEEP 和固定 DeepSearch 子图的推演；第 16 节以后记录第二轮讨论形成的修正版结论。两者冲突时，以第 16 节以后的结论为准。旧结论仍保留，用于说明方案为何发生变化。

## 1. 这次讨论究竟在解决什么问题

表面问题是：ke-engine 应该采用什么样的 Intent、RAG 和 Agent 架构。

真正的问题是：

> 已经知道新一代 Agent 架构可能是什么样以后，应该如何增强过去做过的企业 RAG 项目，既体现技术成长，又不把旧项目直接重写成后续 Agent 项目？

这件事同时受到四个条件约束：

1. LLMentor know-engine 是真实业务项目，是 ke-engine 的业务原型和经验来源。
2. ke-engine 是对已有项目的盘点、重构和增强，未来需要作为一个 RAG 项目写入简历。
3. DeerFlow 1.x 是上一代 Agentic Workflow 的重要参考，但它是 Deep Research 场景，不应被表面上的“搜索”二字限制理解。
4. 后续还会盘点一个更复杂的 Agent 项目，它将承载分层意图、Master/SubAgent、Tool/Skill/MCP、Hooks、长期记忆和复杂执行等能力。

因此，讨论一直在两个风险之间摆动：

- 如果 ke-engine 过于保守，就只是把 know-engine 再实现一遍，缺少技术升级。
- 如果 ke-engine 过于先进，就会提前变成后续 Agent 项目的缩小版，两个简历项目失去差异。

## 2. 三个项目在讨论中的定位

### 2.1 LLMentor know-engine：真实业务基础

know-engine 代表的是上一阶段的企业级 RAG 实践。其核心链路可以概括为：

```text
用户问题
  ↓
IntentRecognitionService
  ↓
related=false ──▶ 普通对话
  ↓ related=true
KnowEngineQueryTransformer
  ↓
KnowEngineQueryRouter
  ↓
向量 / 全文 / SQL / Neo4j Retriever
  ↓
RetrievalAugmentor
  ↓
按业务 intent 选择 Prompt 并生成回答
```

它的主要价值不是“Agent 架构”，而是已经落入真实企业场景的工程能力：

- 业务意图识别；
- 汽车领域实体提取；
- 多轮会话记忆；
- 查询改写；
- 多数据源路由；
- 向量、全文、关系数据和图数据检索；
- Rerank 和内容聚合；
- 不同意图对应不同 Prompt；
- 流式输出与消息持久化。

它本质上是一个中心化的 RAG Workflow：

- `ChatApplicationService` 是控制流中心；
- `IntentRecognitionService` 是统一语义入口；
- 改写、路由、检索、生成由不同专业组件完成；
- LLM 参与多个环节，但应用代码决定整体执行顺序。

它不是中心化 Coordinator Agent，也不是 Multi-Agent 系统。

### 2.2 DeerFlow 1.x：上一代 Agentic Workflow 参考

DeerFlow 1.x 没有跳出 Workflow 的本质，但尽可能让 LLM 参与流程控制：

```text
START
  ↓
Coordinator
  ├── direct_response ──▶ END
  ├── clarification ────▶ 等待用户
  └── handoff_to_planner
              ↓
           Planner
              ↓
    Researcher / Analyst / Coder
              ↓
           Reporter
              ↓
             END
```

它的重要特征是：

- Coordinator 不是输出机械的分类字段，而是选择 Handoff Tool；
- Handoff Tool 表达执行权转移；
- LangGraph `Command(goto=...)` 控制下一节点；
- Planner、Researcher、Reporter 的位置和关系仍由固定图预先定义；
- 它属于 Agentic Workflow，而不是新一代通用 Agent Runtime。

本次讨论逐渐形成的认识是：DeerFlow 的 DeepSearch 不应被理解为一种狭窄的“搜索意图”。它更像复杂任务或复杂对话的执行方案：

```text
理解目标
→ 规划问题
→ 多轮取证
→ 综合分析
→ 形成报告
```

比较、分析、跨来源验证、多约束咨询等高难任务都可能进入 DeepSearch。

### 2.3 后续 Agent 项目：新一代 Agent Runtime

后续项目的定位明显更高一层，主链路包括：

- L1 规则、L2 向量、L3 LLM 的分层意图降级；
- 单意图高置信度时跳过 MasterAgent；
- 多意图或低置信度时由 MasterAgent 调度；
- 通过 SubAgentTool 调用不同 SubAgent；
- Tool、Skill、MCP、RAG 和长期记忆；
- Hooks、ProgressNotifier、SessionPersistence、CircuitBreaker；
- message、thinking、progress、user_interaction 等多类型 SSE；
- 更通用的任务生命周期和执行治理。

它的核心问题是：

> 如何理解复杂任务，并动态调度多个专业执行单元和外部能力完成任务？

ke-engine 即使增加 Agentic 能力，也不应提前拥有这一整套 Runtime。

## 3. 讨论过程回顾

以下不是逐字聊天记录，而是按照思路变化重新整理的推演过程。

### 3.1 起点：DeerFlow 1.x 是否做了传统意图识别

最初关注的是 DeerFlow 1.x 是否存在专门的 Intent Recognition。

结论是：DeerFlow 没有 know-engine 这种独立、业务枚举化的传统意图分类器。Coordinator 通过 Prompt 和 Tool Calling，在以下行为之间选择：

- 直接回答；
- 澄清；
- Handoff 给 Planner 开始研究。

它识别的不是细粒度业务 intent，而是当前请求应该采用何种交互和执行模式。

### 3.2 多轮对话与“它呢？”问题

随后讨论了多轮对话中的代词、指代和省略问题。

一开始形成过一个判断：Coordinator 之前应该增加 Query Rewrite 或 Context Resolution，否则“它呢？”可能导致错误路由。

继续检查 know-engine 后，这个判断被修正：

- know-engine 的 `IntentRecognitionService` 本身通过 `conversationId` 使用会话记忆；
- 当前实现保留的是最近 10 条消息，通常约等于 5 轮问答，而不是 10 个完整轮次；
- Intent 节点具备结合历史理解“它呢？”的条件；
- 进入 RAG 后，`KnowEngineQueryTransformer` 会再次读取历史，将问题改写成独立检索问题。

所以，下面这条链路本身可以工作：

```text
带历史的 Intent Recognition
  ↓
判断属于专业问题
  ↓
Query Transformer 根据历史完成指代消解和独立问题改写
```

真正的风险不是“Intent 完全看不到上下文”，而是 Intent 是一个硬门控：如果短问题被错误判为 `related=false`，后面的 QueryTransformer 就没有执行机会。

因此，合理的增强方向不是必然增加一个前置 Context Agent，而是：

- 强化多轮 Intent Prompt；
- 增加代词、省略、主题切换的多轮评测样本；
- 增加低置信度与澄清路径；
- 避免使用 `related` 一个字段同时表达领域相关性和是否需要 RAG。

### 3.3 第一次方案：把 IntentRecognitionService 改成 Coordinator

曾经提出过：

> IntentRecognitionService 只是 LLM 参与的机械路由，能否改成 Coordinator，并把 RAG、Clarify 作为 Tool？

这个方向的优点是：

- LLM 结合完整上下文做决策；
- “它呢？”可以在生成 Tool 参数时完成语义补全；
- 不必依赖大量字符串字段承载隐式语义；
- 能通过 Handoff 把执行权交给专业路径。

但很快暴露出一个问题：如果 Coordinator 同时负责普通对话、问题改写、意图识别、RAG 决策、澄清和结果判断，它就会成为一个过强的中心节点。

### 3.4 对“中心化”的反复辨析

讨论中尝试过把 Coordinator 改名为：

- Contextual Router；
- Query Understanding Node；
- Intent Routing Agent；
- RAG Coordinator。

后来确认：名字不会改变拓扑。

只要所有请求都先经过一个节点，并由它决定所有后续路径，它就是中心路由。下面两种写法在架构上没有本质区别：

```text
IntentRecognitionService
→ 返回 route 字段
→ 应用代码 if/else
```

```text
Intent Agent
→ 选择 Handoff Tool
→ Command(goto)
```

Handoff 可以让路由更 Agentic、更贴近“执行权转移”，但不能自动消除中心化。

由此得到一个重要认识：

> 中心化并不天然错误。真正需要判断的是，中心节点只负责入口分流，还是把所有执行职责也集中到自己身上。

### 3.5 第二次方案：把 Agentic 能力分散到多个 RAG 节点

为了避免一个过强 Coordinator，讨论过一条更分散的链路：

```text
Context Understanding
→ Intent Recognition
→ Query Planning
→ Retrieval Router
→ RAG MCP
→ Evidence Grading
→ Grounded Answer
```

随后又进一步提出：

```text
Plan-Execute
→ ReAct
→ Reflection
```

并将 RAG、Web Search、HITL 作为 ReAct 工具。

这个方案在技术上成立，但产生了新的疑虑：

- 是否为了体现 Agentic 而预设太多节点；
- 简单专业问答是否值得付出多次模型调用；
- Reflection 是否有真实评测数据支持，还是装饰性节点；
- ke-engine 是否会提前变成后续 Agent 项目的缩小版；
- 简历重心是否会从 RAG 工程偏移到 Agent 调度。

最终阶段性判断是：不能把 Plan-Execute、ReAct、Reflection 全部默认塞进每个 RAG 请求中。

### 3.6 一度回撤：只做 know-engine 的适度增强

由于担心用力过猛，讨论一度回到更保守的方案：

```text
Context-aware Intent
→ Chat / Clarify / RAG
→ Query Transformer
→ RAG MCP
→ Grounded Answer
```

这个方案可以把主要精力投入：

- 文档解析；
- 分块；
- 混合检索；
- Rerank；
- 权限过滤；
- 引用溯源；
- 无答案拒答；
- RAG 评测；
- 流式输出和生产工程。

但它再次暴露出前面的问题：所谓 Context-aware Intent Agent 仍然是中心路由，只是没有叫 Coordinator。

### 3.7 关键转折：重新定义 DeepSearch

最后的关键转折来自对 DeepSearch 的重新理解：

- DeepSearch 不是某一种特定业务意图；
- 它是复杂任务或复杂对话的执行强度；
- 简单问题不需要规划和多轮工具调用；
- 高难问题天然适合进入 DeepSearch；
- 用户还可以像选择 ChatGPT 高级模式一样，显式选择执行强度。

这样，系统的顶层问题不再是：

```text
“用户属于哪个业务 intent？”
```

而是：

```text
“这个请求应该直接回答、简单查询知识，还是进入复杂任务执行？”
```

由此，DeerFlow 1.x 风格的 Coordinator 得到了更充分的业务理由。

它不再只是为了显得 Agentic 而存在，而是负责在不同执行强度之间分流。

## 4. 当前阶段的架构倾向

当前最符合全部讨论的方案，是“双执行强度 + 固定 DeepSearch 子图”。

```text
用户输入
· message
· conversation_id
· execution_mode: AUTO / DEEP
        │
        ▼
Execution Mode Gate
        │
        ├── DEEP ─────────────────────────────────────┐
        │                                              │
        └── AUTO                                       │
              │                                        │
              ▼                                        │
        Coordinator Agent                              │
              │                                        │
       ┌──────┼───────────┬──────────────┐             │
       │      │           │              │             │
       ▼      ▼           ▼              ▼             │
    DIRECT  KNOWLEDGE   CLARIFY       DEEPSEARCH ◀─────┘
       │      │           │              │
       │      │           │              ▼
       │      │           │       Planner
       │      │           │              │
       │      │           │              ▼
       │      │           │       Researcher ReAct
       │      │           │        ├── RAG MCP
       │      │           │        ├── Web Search
       │      │           │        └── HITL
       │      │           │              │
       │      │           │              ▼
       │      │           │          Reporter
       │      │           │              │
       │      ▼           ▼              ▼
       │  Query Rewrite  interrupt      Report
       │      │
       │      ▼
       │   RAG MCP
       │      │
       │      ▼
       │ Grounded Answer
       │      │
       └──────┴──────────────────────────────────────▶ END
```

### 4.1 AUTO 模式

AUTO 模式下，Coordinator 结合对话历史和当前请求，在以下路径中选择：

- `DIRECT`：闲聊、能力说明、无需专业知识的问题；
- `KNOWLEDGE`：边界明确、一次知识查询即可解决的问题；
- `CLARIFY`：任务目标或关键实体不足；
- `DEEPSEARCH`：需要规划、多轮检索、跨来源验证或综合分析的问题。

Coordinator 负责入口分流，但不负责复杂任务执行。

### 4.2 DEEP 模式

用户显式选择高级模式时：

```text
execution_mode = DEEP
→ 直接进入 DeepSearch
```

模型不应该因为“问题看起来简单”而擅自降级。

但 DeepSearch 内部仍然可以发现信息不足，并通过 HITL 请求用户补充。

当前认可的优先级是：

```text
安全与权限约束
    >
用户显式执行模式
    >
系统复杂度判断
    >
Agent 的工具选择
```

### 4.3 简单 Knowledge 路径

简单专业知识问题不进入 Planner 和 ReAct：

```text
Coordinator
→ Query Rewrite
→ RAG MCP
→ Grounded Answer
```

示例：

- “宋PLUS首保是多少公里？”
- “发动机故障灯亮了怎么办？”
- “自适应巡航怎么打开？”

该路径强调低延迟、引用、拒答和专业 Prompt。

### 4.4 DeepSearch 路径

复杂任务进入固定子图：

```text
Planner
→ Researcher ReAct
→ Reporter
```

示例：

- “结合最近三次保养记录和维修手册，分析车辆抖动的可能原因和处理优先级。”
- “对比宋PLUS和唐DM-i的使用成本、安全配置和家庭适用场景。”
- “结合内部产品资料和公开信息，分析竞品近期变化。”

Researcher 当前考虑的固定工具是：

- `rag_search`：查询企业内部知识；
- `web_search`：查询公开和时效性信息；
- `request_human_input`：补充关键条件或确认研究范围。

第一版不默认增加独立 Reflection 节点。Researcher 根据 Observation 完成局部判断，Reporter 负责最终综合。只有评测证明“计划已执行但证据覆盖仍经常不足”时，再考虑加入 Reflection 或 Replan。

## 5. RAG MCP 在架构中的位置

RAG 做成 MCP 是当前比较稳定的设想，但 MCP 不等于 Agent 架构。

同一个 RAG MCP 可以被两条路径复用：

```text
简单 Knowledge 路径 ───────▶ RAG MCP

DeepSearch Researcher ──────▶ RAG MCP

未来 Knowledge SubAgent ───▶ RAG MCP
```

因此，RAG MCP 是跨项目复用的知识能力，不负责整个对话系统的调度。

当前倾向是让 RAG MCP 提供结构化证据和引用，而不是只返回一个无法观察的最终字符串答案。其内部可以逐步承载：

- Query Expansion；
- Dense + BM25 Hybrid Retrieval；
- Metadata/ACL Filter；
- 多路召回；
- Rerank；
- Context Compression；
- 文档和片段引用；
- 检索诊断信息。

最终答案由 ke-engine 的简单回答节点或 DeepSearch Reporter 根据证据生成。

## 6. Handoff 的认识变化

讨论中对 Handoff 的认识经历了三次变化。

### 第一阶段：把 Handoff 等同于 Multi-Agent

最初担心使用 Handoff 会直接滑向 Master/SubAgent，因此一度建议 ke-engine 完全不使用 Handoff。

### 第二阶段：确认 Handoff 是控制机制

随后确认，Handoff 本身只是一种控制面表达：

```text
LLM 选择 Handoff Tool
→ 图读取 Tool Call
→ Command(goto=目标节点)
```

它可以用于固定 Workflow 节点之间的执行权转移，并不必然意味着动态 Multi-Agent。

### 第三阶段：确认 Handoff 不会消除中心化

即使使用 Handoff，只要所有路径都由 Coordinator 选择，入口仍然是中心化的。

因此最终认识是：

> Handoff 的价值是表达执行权转移，不是消灭中心路由；是否采用它，应看目标节点是不是一段具有独立职责的执行流程。

在当前倾向中，以下 Handoff 是合理的：

- `handoff_to_knowledge`；
- `handoff_to_deepsearch`；
- `handoff_after_clarification`。

因为它们代表不同执行模式，而不仅仅是一个普通 `if/else` 标签。

## 7. 关于中心化的当前结论

know-engine 和 DeerFlow 1.x 都有中心入口，只是中心的性质不同。

| 维度 | know-engine | DeerFlow 1.x / 当前 ke-engine 倾向 |
|---|---|---|
| 入口中心 | IntentRecognitionService | Coordinator |
| 控制主体 | ChatApplicationService | Coordinator + LangGraph |
| 决策表达 | `related`、`intent` 字段 | Tool Call / Handoff |
| 路由执行 | 应用代码 `if/else` | `Command(goto)` |
| 直接回答 | 另一个 Chat Service | Coordinator 可直接回答 |
| 复杂任务 | 固定 RAG | Handoff 到 DeepSearch |
| 本质 | 中心化 RAG Workflow | 中心化 Agentic Workflow |

当前不再追求“完全去中心化”。真正的边界是：

- Coordinator 只做会话入口、执行强度判断和 Handoff；
- 简单知识问答由固定知识路径执行；
- 复杂任务由 DeepSearch 子图执行；
- Coordinator 不亲自完成规划、工具循环和报告生成。

这种中心化是有意识的架构选择，而不是通过改名掩盖的事实。

## 8. 当前明确不做或延后的内容

### 8.1 暂不做

- 通用 MasterAgent；
- 动态 SubAgent 注册和发现；
- Tool/Skill/MCP 统一能力市场；
- 通用 Agent Hooks/Harness；
- 跨任务长期记忆；
- 任意复杂任务生命周期；
- L1/L2/L3 通用意图降级；
- 默认在所有知识问题中运行 Planner；
- 默认增加独立 Reflection/Replan；
- 把每个 Workflow Node 都包装成 Agent。

### 8.2 等真实需求或评测再决定

- 是否需要 Reflection 节点；
- 是否允许 DeepSearch 自动多次 Replan；
- Web Search 是否只做 RAG 不足后的补充，还是可以由 Planner 直接选择；
- 简单 Knowledge 路径是否需要轻量 Tool Calling；
- 是否需要 FAST、AUTO、DEEP 三档，还是只保留 AUTO、DEEP 两档；
- DeepSearch 是否需要计划确认；
- RAG MCP 返回纯证据、候选答案，还是同时暴露两类接口；
- DeepSearch 的最大步骤数、工具调用数和执行时间预算。

## 9. 与后续 Agent 项目的差异

两个项目可以共享 RAG MCP，也可以在能力上形成覆盖，但架构问题不同。

### ke-engine

```text
固定 Coordinator
固定 Handoff 目标
固定 Knowledge 路径
固定 DeepSearch 子图
固定 RAG / Web / HITL 工具
聚焦知识问答和复杂知识研究
```

它解决的是：

> 如何根据问题复杂度选择回答强度，并通过企业内部知识和外部资料形成可靠答案？

### 后续 Agent 项目

```text
分层意图识别
动态 MasterAgent
多个业务 SubAgent
SubAgentTool / Handoff
Tool / Skill / MCP 能力体系
Hooks / CircuitBreaker / SessionPersistence
长期任务和复杂执行生命周期
```

它解决的是：

> 如何理解包含多个意图的复杂任务，并动态组织专业 Agent 和工具持续执行？

两者的差异不是“有没有 Agent”，而是：

```text
ke-engine：固定拓扑上的 Agentic Workflow

后续项目：可扩展 Agent Runtime 上的动态任务调度
```

## 10. 项目时间背景与简历叙事

本次讨论特别强调了技术时代背景。

ke-engine 对应的真实项目参与时间约为 2025 年 8 月至 2026 年 1 月，项目立项更早。当时企业 RAG、Workflow 编排和 LangGraph 已经有实际落地空间，但新一代 Agent Runtime、Skills、通用 Harness 和成熟 Multi-Agent 工程体系仍在快速演进。

因此简历中不应该把 ke-engine 描述成一开始就完成了当前最先进的通用 Multi-Agent 平台。

更可信的叙事是：

1. 原始 know-engine 已经完成企业 RAG 的业务闭环；
2. ke-engine 对其进行工程化重构，并参考 DeerFlow 1.x 增加固定 Workflow 内的 Agentic 分流和复杂任务模式；
3. 随着任务从知识问答扩展到多意图、跨能力和长期执行，固定 Workflow 的局限逐渐显现；
4. 后续项目进一步演进为 Master/SubAgent 和 Agent Runtime。

这是一条连续、可信的技术成长线：

```text
LLM 增强业务流水线
    ↓
LLM 参与固定 Workflow 决策
    ↓
Agent 成为复杂任务的执行主体
```

## 11. 建议的建设顺序

本文只记录方向，不替代后续正式设计。按照当前认识，建设顺序应为：

### 第一阶段：保持当前 Chat 运行时稳定

- 继续使用已有 LangGraph checkpoint；
- 保持业务消息和 Graph State 分离；
- 保持 SSE producer 与连接生命周期解耦；
- 不破坏现有 `START → llm → END` 的生产基线。

### 第二阶段：打通简单 Knowledge 闭环

```text
Query Rewrite
→ RAG MCP
→ Grounded Answer
→ Citation
```

优先验证真实 RAG 质量，而不是先搭建复杂 Agent 外壳。

### 第三阶段：增加 AUTO / DEEP 执行强度

- 增加请求级执行模式；
- AUTO 模式接入 Coordinator；
- 简单问题走 Direct 或 Knowledge；
- 用户选择 DEEP 时直接进入 DeepSearch。

### 第四阶段：实现固定 DeepSearch 子图

```text
Planner
→ Researcher ReAct
→ Reporter
```

Researcher 只开放固定工具：RAG MCP、Web Search、HITL。

### 第五阶段：用评测决定是否继续增强

只有出现可量化问题时再增加：

- Reflection；
- Replan；
- 更多检索工具；
- 更复杂的计划管理；
- 更长的执行预算。

## 12. 容易再次陷入的误区

| 误区 | 表现 | 提醒 |
|---|---|---|
| 把最新架构等同于当前项目最优架构 | 知道新 Agent Runtime 后，希望 ke-engine 也全部采用 | 架构需要匹配项目时间、业务复杂度和简历定位 |
| 为了 Agentic 而增加节点 | 预先加入 Planner、Reflection、Replan | 先用评测证明固定链路解决不了问题 |
| 通过改名掩盖中心化 | 把 Intent Service 改名成 Router/Coordinator | 看控制流拓扑，不看名字 |
| 把 Handoff 等同于去中心化 | 使用 Tool Call 后认为系统不再中心化 | Handoff 只是执行权转移协议 |
| 把 DeepSearch 当成搜索意图 | 只允许资料搜索问题进入 | DeepSearch 是复杂任务执行强度 |
| 把所有问题都送入 DeepSearch | 简单 FAQ 也规划、反思、多轮工具调用 | 保留低延迟 Knowledge 快路径 |
| 把 RAG 做成不可观察的大工具 | MCP 只返回最终字符串 | 优先返回证据、引用和检索诊断 |
| 提前复制后续项目 | 在 ke-engine 引入 Master/SubAgent/Harness | 固定子图与通用 Runtime 必须保持边界 |

## 13. 第一轮阶段性结论

截至本次讨论，最重要的结论如下：

1. know-engine 是真实业务基础和 RAG 内部设计来源，但它属于中心化 RAG Workflow。
2. DeerFlow 1.x 更适合作为 ke-engine 的上层 Agentic Workflow 参考。
3. DeepSearch 应理解为复杂任务/复杂对话执行模式，而不是一种特定搜索意图。
4. 系统需要支持 AUTO 和用户显式 DEEP 两种执行强度；用户显式选择优先于模型降级判断。
5. AUTO 模式下由 Coordinator 在 Direct、Knowledge、Clarify、DeepSearch 之间分流。
6. Coordinator 的中心化是明确接受的，但其职责应限制在入口交互和执行强度判断。
7. 简单知识问题走 Query Rewrite → RAG MCP → Grounded Answer，不进入 Planner/ReAct。
8. 复杂问题走固定的 Planner → Researcher ReAct → Reporter 子图。
9. Researcher 可使用 RAG MCP、Web Search 和 HITL 三类固定工具。
10. 第一版不默认加入独立 Reflection，是否增加由后续评测决定。
11. RAG MCP 是可跨 ke-engine 和后续 Agent 项目复用的知识能力边界。
12. 后续 Agent 项目的核心仍是动态 Master/SubAgent Runtime，不会因为 ke-engine 有固定 DeepSearch 子图而失去差异。

## 14. 下次继续讨论时应先回答的问题

为了避免下一次重新从头摇摆，后续讨论建议直接从以下问题继续：

1. AUTO / DEEP 是否已经足够，是否真的需要 FAST？
2. Coordinator 判断复杂度的明确标准是什么？
3. Knowledge 和 DeepSearch 是否共用同一套 RAG MCP 输入输出协议？
4. RAG MCP 返回证据包还是最终答案？当前倾向是证据包。
5. Web Search 是 DeepSearch 的平级工具，还是只能在内部知识不足时使用？
6. HITL 需要支持哪些场景：补充信息、确认计划、权限确认，还是三者都支持？
7. DeepSearch 的 Planner、Researcher、Reporter 是否都需要独立模型配置？
8. DeepSearch 第一版的步骤数、工具调用次数和总超时应该如何限制？
9. 哪些指标证明需要增加 Reflection？
10. 哪些能力明确留到后续 Agent 项目，不允许继续加入 ke-engine？

在这些问题得到确认以前，不应直接进入完整 DeepSearch 实现。

## 15. 第一轮一句话回顾

> ke-engine 不再被限定为 know-engine 的机械重写，也不直接跃迁成新一代 Multi-Agent Runtime；它以 DeerFlow 1.x 的固定 Agentic Workflow 为上层参考，以 know-engine 的企业 RAG 能力为业务基础，通过 AUTO/DEEP 执行强度、简单知识快路径、固定 DeepSearch 子图和可复用 RAG MCP，形成连接两个技术阶段的中间项目。

## 16. 第二轮讨论为什么重新打开了结论

第一轮讨论解决了“ke-engine 是否应该完全复制 know-engine，或者直接升级成 Multi-Agent Runtime”的问题，但仍然留下了一个更贴近项目目的的疑问：

> ke-engine 是用于复盘真实企业项目并写入简历的 RAG 项目。它的 Chat 链路究竟需要做到什么程度？是否有必要为了吸收 DeerFlow 1.x 而加入完整 DeepSearch？

这轮讨论重新强调了两个约束：

1. ke-engine 需要体现相对于原始企业项目的技术成长，但不能为了“先进”而加入没有业务需求支撑的 Agent 架构。
2. 后续还有一个更先进的 Agent 项目，需要承载 Master/SubAgent、分层意图、Tool/Skill/MCP、Hooks、长期记忆和复杂任务生命周期。两个简历项目不能重复讲述同一套能力。

由此，项目的目标函数不再是“让 ke-engine 的 Agent 架构尽可能好”，而是：

```text
真实性
+ 技术升级
+ 简历差异化
+ 可解释的演进关系
```

这意味着第一个项目不应被故意做弱，但应该沿 RAG、业务知识服务和生产工程方向深入；第二个项目则沿动态 Agent Runtime 方向深入。

## 17. 对项目定位的进一步澄清

### 17.1 项目不是汽车知识引擎的简单迁移

LLMentor know-engine 的汽车场景只是代码参考和业务经验来源。ke-engine 对应的真实业务背景主要是：

- 铁路运输；
- 煤炭运输；
- 销售业务；
- 企业制度、合同、规程和业务知识；
- 合同、订单、发运、销售等结构化业务数据。

汽车领域的车型、车辆、维保、营销等概念可以迁移为：

| know-engine 示例 | ke-engine 业务示例 |
|---|---|
| 车型、车辆 | 客户、供应商、煤种、合同、订单 |
| 保养时间 | 发运时间、到站时间、合同周期 |
| 汽车配置 | 煤炭质量指标、运输线路、业务规则 |
| 维修问题 | 运输异常、数量异常、执行偏差 |
| 营销政策 | 销售政策、价格政策、合同条款 |

架构可以迁移，但真实业务实体、权限、数据源、口径和澄清条件必须保留，否则项目会退化成没有业务约束的通用 Demo。

### 17.2 项目也不再抽象成通用 RAG 平台

讨论中一度考虑把 ke-engine 抽象为适用于任意行业的知识平台，并引入 AssistantProfile、领域插件、动态 Retriever 注册和通用知识空间编排。最终放弃这一方向。

当前定位是：

> 面向铁路、煤炭运输和销售业务的企业知识引擎，在代码层保持合理模块边界，但不建设任意行业插件市场或通用 SaaS 平台。

因此不为了抽象而增加：

- 任意领域插件注册；
- 动态 AssistantProfile 管理平台；
- 通用工具市场；
- 面向未知行业的 Prompt 配置中心；
- 任意 Retriever SPI 市场；
- 为多租户 SaaS 设计的额外产品模型。

### 17.3 RAG MCP 仍然是公共能力

业务向并不意味着 RAG 只能由当前 Chat 使用。RAG MCP 的复用范围被明确为企业内部多个应用：

```text
ke-engine Chat ──────────┐
其他客服系统 ────────────┤
后续 Agent 项目 ─────────┼──▶ RAG MCP
内部业务应用 ────────────┘
```

所以 RAG 做成 MCP 不是为了展示 Agent 技术，也不是当前 Chat 的内部实现细节，而是知识库能力本身需要跨项目复用。

## 18. 对六个关键争议的修正

### 18.1 Coordinator 是否直接生成回答取决于模型策略

第一轮倾向让 Coordinator 直接回答闲聊和简单问题。第二轮曾提出让 Coordinator 只路由、再由独立 Direct Answer 节点生成，但最终确认这不应成为架构硬约束。

如果当前模型本身具备通用对话能力，可以像 DeerFlow 一样：

```text
Coordinator
→ direct_response
→ END
```

如果后续使用专业领域微调模型，非业务问题能力可能下降，则可以：

```text
Coordinator
→ NON_BUSINESS
→ 通用模型回答或能力范围引导
```

因此逻辑上保留非业务回答路径，物理上是否增加一次模型调用由模型部署和成本评测决定。

### 18.2 Clarify 从来不是终态

第一轮架构中的 Clarify 与 DeerFlow 一样，依赖 interrupt/resume：

```text
执行节点发现信息不足
→ interrupt
→ 用户补充
→ Command(resume)
→ 恢复原执行上下文
```

Clarify 可以由入口业务理解触发，也可以由执行中的 Business Knowledge Agent 触发。它不是与回答并列的最终结果。

### 18.3 MCP 是公共知识服务协议

RAG MCP 的目标是让当前 Chat、其他客服、内部业务系统和后续 Agent 项目共享同一套知识检索能力。内部是否仍有领域 Service 或 Adapter 不改变 MCP 作为对外能力边界的事实。

### 18.4 RAG 内部链路不是顶层争议

Query Rewrite、Dense/BM25、Fusion、Rerank、Context Compression、Evidence Package 等属于 RAG 内部设计。它们需要做深，但不决定 Chat 是否需要 DeepSearch。

### 18.5 ReAct 不等于用力过猛

受限 ReAct 是业务知识 Agent 的合理基础能力：

```text
理解问题
→ 调用 RAG MCP 或结构化查询工具
→ 观察证据
→ 调整查询或补充条件
→ 必要时再次调用工具
→ 证据充分后回答
```

“不要用力过猛”并不意味着退回一次路由、一次检索、一次生成的固定流水线。真正需要避免的是动态 Agent 团队、通用任务规划和没有业务必要性的 Deep Research。

### 18.6 真正的争议是是否需要 DeepSearch

DeepSearch 的核心产物是多步骤研究和综合报告：

```text
复杂目标
→ 研究计划
→ 多轮跨来源取证
→ 综合分析
→ 长报告
```

当前明确业务目标则是：

```text
知识库问答
+ 企业业务客服
+ 结构化业务数据查询
+ 必要时的多轮工具调用和澄清
```

在没有真实研究报告需求和对应评测集以前，主 Chat 不需要接入完整 DeepSearch。

## 19. 从 know-engine 继承、抛弃和增强什么

### 19.1 继承的业务与 RAG 能力

- 企业知识库完整闭环；
- 领域意图识别；
- 领域实体提取；
- 多轮上下文理解；
- Query Rewrite；
- 向量、全文、SQL 和图数据检索经验；
- 多路内容聚合与 Rerank；
- 文档权限过滤；
- 不同业务意图使用专业 Prompt；
- 流式输出、会话和消息持久化。

这些内容代表真实企业项目的业务基础，是 ke-engine 的主体，而不是需要被 Agent 架构替换的旧包袱。

### 19.2 抛弃或重构的部分

- 用 `related` 一个布尔字段同时承担领域判断和 RAG 硬门控；
- Intent 误判后不再给检索链路补救机会；
- 所有职责集中在 ChatApplicationService；
- 每次请求临时装配大量 Retriever、模型和 Augmentor；
- 固定最近 10 条消息作为完整记忆方案；
- Query Rewrite 完全覆盖原始问题；
- 路由只选择一种检索策略；
- 使用 `[PROGRESS]`、`[WARN]`、`[CARD]`、`[DONE]` 等字符串前缀表达事件；
- 缺少统一证据、引用、拒答和评测闭环。

### 19.3 ke-engine 的增强方向

- 用 LangGraph 表达可恢复的业务 Chat 状态；
- 将业务历史和 Graph checkpoint 分离；
- 将领域意图、实体、权限和数据口径纳入业务理解；
- 允许原始问题、上下文消解问题和扩展查询共同参与检索；
- 支持 Dense + BM25、多路 Fusion、Rerank 和可观察检索诊断；
- 将 RAG 作为 MCP 公共能力对外提供；
- 允许 Business Knowledge Agent 通过受限 ReAct 多次调用固定工具；
- 综合非结构化知识和结构化业务数据；
- 增加证据校验、引用、拒答和业务口径说明；
- 建立检索、回答和多轮 Chat 评测。

## 20. 从 DeerFlow 1.x 吸收、抛弃和延后什么

### 20.1 吸收的控制机制

- 固定 LangGraph Workflow；
- LLM 通过 Tool Calling 表达执行选择；
- 使用 `Command(goto)` 控制固定节点跳转；
- Handoff 表达执行权转移，但不把它等同于 Multi-Agent；
- interrupt/resume 驱动可恢复澄清；
- Checkpoint 保存 Graph 推理状态；
- 受限 ReAct 工具循环；
- 模型按职责配置；
- 最大澄清轮数、工具调用数和执行时间预算；
- 工具异常、模型未调用工具时的降级路径。

### 20.2 不继承的业务拓扑

第一版不采用：

- Coordinator → Planner → Research Team → Reporter；
- Background Investigator；
- Researcher、Analyst、Coder 多角色；
- 研究计划生成与确认；
- 自动 Replan；
- Deep Research 长报告；
- 默认 Web Search；
- 自动判断并进入 DeepSearch。

ke-engine 借鉴的是 DeerFlow “如何控制固定 Agentic Workflow”，而不是复制它“如何完成 Deep Research”。

### 20.3 保留的未来扩展点

如果未来出现真实的跨来源研究报告需求，并且受限 ReAct 无法稳定完成，可以增加独立 `research_subgraph`：

```text
planner
→ researcher
→ reporter
```

该子图不进入第一版主 Chat，也不作为当前简历项目的主要叙事。

## 21. 修正后的目标架构

### 21.1 总体分层

```text
┌────────────────────────────────────────────┐
│                业务应用层                  │
│  知识库问答 / 运输客服 / 销售客服          │
└───────────────────┬────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────┐
│              Chat Workflow                 │
│  业务上下文理解                            │
│  领域意图与实体                            │
│  非业务问题处理                            │
│  Clarify / interrupt / resume              │
│  Business Knowledge Agent                  │
│  受限 ReAct                                │
└──────────────┬─────────────────┬───────────┘
               │                 │
               ▼                 ▼
┌──────────────────────┐  ┌─────────────────┐
│       RAG MCP        │  │ 结构化业务查询  │
│ 制度、合同、规程     │  │ 合同、订单      │
│ 产品与业务知识       │  │ 发运、销售数据  │
│ Hybrid / Rerank      │  │ SQL Tool        │
└──────────┬───────────┘  └────────┬────────┘
           │                       │
           └───────────┬───────────┘
                       ▼
              Grounded Business Answer
```

### 21.2 主 Chat 链路

```text
START
  ↓
加载运行上下文
· conversation_id
· user_id
· 用户角色与数据权限
· 当前业务系统来源
  ↓
Business Understanding
· 结合会话历史理解问题
· 识别业务意图
· 提取业务实体
· 判断信息是否完整
  ↓
执行决策
  ├── NON_BUSINESS
  │      └── 当前模型直接回答，或切换通用模型/能力引导
  │
  ├── CLARIFY
  │      └── interrupt → 用户补充 → 恢复原执行上下文
  │
  └── BUSINESS
         ↓
      Business Knowledge Agent
         ├── RAG MCP：制度、合同、规程和业务知识
         ├── SQL Tool：合同、订单、发运和销售数据
         └── request_human_input：补充必要业务条件
         ↓
      Evidence Validation
         ├── 证据充分 → 生成回答
         ├── 证据冲突 → 说明来源和口径
         ├── 可以补检索 → 回到 Agent
         └── 无可靠证据 → 拒答或澄清
         ↓
      Grounded Business Answer
      · 业务结论
      · 数据口径
      · 文档引用
      · 风险提示
  ↓
持久化业务消息并完成 SSE
  ↓
END
```

### 21.3 ReAct 的边界

Business Knowledge Agent 可以：

- 调整检索表达；
- 增加或修正业务过滤条件；
- 多次调用 RAG MCP；
- 根据问题组合 RAG MCP 和 SQL Tool；
- 在缺少客户、合同、时间范围等条件时请求用户补充；
- 根据证据决定回答、继续检索或拒答。

它不可以：

- 创建或发现其他 Agent；
- 动态注册工具；
- 生成开放式长期任务；
- 执行任意代码；
- 自动访问 Web；
- 无限循环、无限 Replan；
- 承担通用复杂任务 Runtime。

## 22. RAG MCP 的当前职责

RAG MCP 聚焦企业知识库证据获取，当前倾向返回结构化 Evidence Package，而不是只返回不可观察的最终字符串：

```text
EvidencePackage
├── evidence_items
│   ├── document_id
│   ├── chunk_id
│   ├── content
│   ├── source
│   ├── metadata
│   ├── retrieval_score
│   └── rerank_score
├── citations
├── applied_filters
├── retrieval_diagnostics
├── warnings
└── trace_id
```

其内部逐步承载：

- Query Rewrite / Query Expansion；
- 原始查询与改写查询并用；
- Dense + BM25 Hybrid Retrieval；
- Metadata / ACL Filter；
- 多路召回与 Fusion；
- Rerank；
- Context Compression；
- 文档和片段引用；
- 检索诊断。

结构化业务查询原则上作为独立 SQL Tool，由 Chat Workflow 控制访问权限和业务口径；是否在未来统一封装进 RAG MCP，由实际复用关系决定，不在本轮提前抽象。

## 23. 与后续 Agent 项目的最终边界

### ke-engine

```text
固定业务 Chat Graph
固定领域意图和实体
固定 RAG / SQL / HITL 工具
受限 ReAct
RAG MCP
证据、引用和拒答
生产级 SSE 与 Checkpoint
```

它解决：

> 如何结合企业知识文档和结构化业务数据，为铁路、煤炭运输和销售人员提供可靠、可追溯的知识问答与业务客服？

### 后续 Agent 项目

```text
L1/L2/L3 分层意图
动态 MasterAgent
多个业务 SubAgent
SubAgentTool / Handoff
Tool / Skill / MCP 能力体系
Hooks / CircuitBreaker / SessionPersistence
长期记忆和复杂任务生命周期
```

它解决：

> 如何理解包含多个意图的复杂任务，并动态组织专业 Agent 和工具持续执行？

两者的关系不再依赖“ke-engine 有没有 Agent”区分，而是：

```text
ke-engine：固定业务拓扑中的 Agentic RAG

后续项目：可扩展 Agent Runtime 中的动态任务调度
```

## 24. 修正后的建设顺序

### 第一阶段：保持现有生产 Chat 基线

- 保持 PostgreSQL Checkpointer；
- 保持 Graph State 与业务消息分离；
- 保持 SSE Producer 与 HTTP 连接生命周期解耦；
- 不破坏当前 `START → llm → END` 的可运行基线。

### 第二阶段：完成 RAG MCP 与简单业务问答

```text
业务问题
→ Query Rewrite
→ RAG MCP
→ Grounded Answer
→ Citation / Refusal
```

优先完成检索质量、权限、引用和评测，不先增加 Agent 外壳。

### 第三阶段：增加 Business Understanding

- 领域意图识别；
- 业务实体和时间范围提取；
- 多轮指代消解；
- NON_BUSINESS / BUSINESS / CLARIFY 决策；
- 可恢复澄清。

### 第四阶段：增加受限 ReAct

- Business Knowledge Agent；
- RAG MCP Tool；
- SQL Tool；
- 最大工具调用次数和总超时；
- Evidence Validation；
- 证据不足时的补检索、澄清和拒答。

### 第五阶段：以评测驱动增强

只有出现可量化问题时再考虑：

- 更复杂的查询规划；
- 更多结构化工具；
- Evidence Compression；
- 更细粒度业务口径校验；
- 独立 Research 子图。

## 25. 修正版阶段性结论

截至第二轮讨论，当前结论为：

1. ke-engine 是面向铁路、煤炭运输和销售场景的业务知识引擎，不再抽象成任意行业通用平台。
2. know-engine 提供真实企业 RAG 的业务闭环、领域理解、多源检索、Rerank、权限和流式交互经验。
3. ke-engine 不复制 know-engine 的 `related` 硬门控、巨型 Application Service、固定消息窗口和字符串事件协议。
4. DeerFlow 1.x 提供 LangGraph、Tool Calling、Handoff、interrupt/resume、受限 ReAct 和运行预算等控制方法。
5. ke-engine 不继承 DeerFlow 的 Planner、Research Team、Reporter、Background Investigator 和默认 Deep Research 业务拓扑。
6. Clarify 是可恢复控制状态，可以在入口理解或工具执行期间发生。
7. ReAct 是业务知识 Agent 的基础能力，不等于通用 Agent Runtime。
8. 主 Chat 第一版不接 DeepSearch；只有真实研究报告需求和评测证明必要时，才增加独立 Research 子图。
9. RAG MCP 是企业内部多个应用复用的知识能力边界，当前倾向返回结构化证据、引用和检索诊断。
10. 结构化业务数据通过固定 SQL Tool 提供，并与 RAG MCP 证据共同支撑业务回答。
11. Coordinator 是否直接回答非业务问题由模型策略决定，不作为固定拓扑要求。
12. ke-engine 的核心技术升级是生产级 RAG、业务理解、可恢复澄清、受限 ReAct、证据治理和生产运行时。
13. 后续 Agent 项目继续承载动态 Master/SubAgent、Tool/Skill/MCP 体系、Hooks、长期记忆和复杂任务生命周期。

## 26. 当前一句话回顾

> ke-engine 继承 know-engine 的真实企业 RAG 业务能力，吸收 DeerFlow 1.x 的固定 Agentic Workflow 控制方式，在铁路、煤炭运输和销售场景中形成“业务理解 + RAG/SQL 受限 ReAct + 可恢复澄清 + 证据化回答”的业务知识 Agent；它不默认承担 Deep Research，也不提前演进成后续项目的通用 Agent Runtime。

## 27. 下一步需要形成的正式设计

本纪要已经确定方向，但仍不替代正式技术规格。下一步应依次明确：

1. Business Understanding 的输入输出和领域意图、实体模型；
2. Chat Graph State 中业务状态、推理状态和持久化状态的边界；
3. RAG MCP 的 Tool Schema、Evidence Package 和错误语义；
4. SQL Tool 的权限、只读约束、查询预算和数据口径；
5. ReAct 的最大步数、最大工具调用数和总超时；
6. Clarify interrupt/resume 的恢复目标和幂等语义；
7. Evidence Validation 的充分、冲突、拒答和补检索标准；
8. SSE 事件类型、顺序和失败语义；
9. 检索、回答、多轮理解和工具调用评测集；
10. 哪些能力继续明确留到后续 Agent 项目。
