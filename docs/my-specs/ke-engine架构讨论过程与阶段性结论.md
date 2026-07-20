# ke-engine 架构讨论过程与阶段性结论

> 记录日期：2026-07-20  
> 文档性质：讨论纪要、思路复盘和阶段性结论，不是正式技术规格，也不是实施计划。  
> 记录目的：保留本轮关于 LLMentor know-engine、DeerFlow 1.x、ke-engine 和后续 Agent 项目之间关系的完整思考过程，避免以后只记得结论，却忘记结论产生的背景、争议和边界。

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

## 13. 当前阶段性结论

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

## 15. 一句话回顾

> ke-engine 不再被限定为 know-engine 的机械重写，也不直接跃迁成新一代 Multi-Agent Runtime；它以 DeerFlow 1.x 的固定 Agentic Workflow 为上层参考，以 know-engine 的企业 RAG 能力为业务基础，通过 AUTO/DEEP 执行强度、简单知识快路径、固定 DeepSearch 子图和可复用 RAG MCP，形成连接两个技术阶段的中间项目。
