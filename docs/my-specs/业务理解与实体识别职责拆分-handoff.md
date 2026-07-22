# 业务理解与实体识别职责拆分 Handoff

> 日期：2026-07-22
> 目的：将 ke-engine 当前 Business Understanding、实体提取和澄清机制的现状、已暴露问题、候选架构及未决问题完整交给后续高级模型审阅。
> 边界：本文只记录分析，不代表已经决定修改方案；当前没有因此调整生产 Graph、Schema、Prompt 或评测数据。

## 1. 希望审阅者回答什么

当前最核心的问题不是如何继续优化一个 Prompt，而是：

> 在一个包含业务路由、RAG、结构化数据查询、工具调用和可恢复澄清的 LangGraph 应用中，实体提取应该属于入口 Business Understanding，属于独立的全局实体识别节点，还是属于具体业务子流程或工具参数生成？

希望高级模型重点审阅：

1. 入口 Business Understanding 是否应继续同时输出 `route + intent + entities + clarification_question`；
2. 实体是否应延迟到具体业务能力已经确定后再提取；
3. 数据查询参数是否应该直接由工具 Schema 表达，而不是维护全局实体模型；
4. 路由澄清和业务参数澄清如何在 Graph 中分层；
5. 多站点、多单据等多值条件应该如何建模和执行；
6. 推荐的目标 Graph 是否符合 LangGraph 的状态、子图、interrupt/resume 和 checkpoint 最佳实践；
7. 如何迁移而不破坏现有 PostgreSQL checkpoint 和正在恢复的会话。

## 2. 项目背景

ke-engine 是一个面向企业铁路运输、煤炭运输和煤炭购销场景的 Chat/RAG 应用。目前 Business Understanding 已实现，真正的业务 RAG、SQL Tool 和业务接口尚未接入；业务请求暂时到达一个固定的 `business_boundary` 节点后结束。

当前业务意图为：

- `POLICY_RULE_QA`：政策、制度和规程；
- `TRANSPORT_OPERATION_QA`：运输生产与调度；
- `COAL_SALES_QA`：煤炭购销与销售；
- `PROFESSIONAL_KNOWLEDGE_QA`：专业知识与技术指导；
- `BUSINESS_DATA_QUERY`：经营数据查询与分析；
- `OTHER_BUSINESS`：其他企业业务。

当前 Graph 使用 LangGraph `Command(update, goto)` 控制流，PostgreSQL saver 持久化 checkpoint，澄清通过 `interrupt()` 挂起并在用户补充后恢复。

## 3. 当前 Graph 现状

当前拓扑可以概括为：

~~~text
START
  ↓
business_understanding
  ├─ NON_BUSINESS → llm → END
  ├─ BUSINESS     → business_boundary → END
  └─ CLARIFY      → clarify
                       ↓ 用户恢复
                  business_understanding
~~~

关键实现：

- `backend/app/domains/chat/graph/builder.py`
- `backend/app/domains/chat/graph/nodes/business_understanding.py`
- `backend/app/domains/chat/graph/nodes/clarify.py`
- `backend/app/domains/chat/graph/nodes/business_boundary.py`
- `backend/app/domains/chat/graph/business_understanding/models.py`
- `backend/app/domains/chat/graph/business_understanding/prompt.py`

`business_understanding` 一次模型调用同时完成：

1. 结合会话历史理解当前问题；
2. 判断 BUSINESS、NON_BUSINESS 或 CLARIFY；
3. 选择业务 intent；
4. 提取所有业务实体；
5. 判断是否缺少执行必需信息；
6. 生成澄清问题。

当前 `BusinessUnderstandingResult` 结构为：

~~~python
class BusinessUnderstandingResult(BaseModel):
    reasoning: str
    route: BusinessRoute
    intent: BusinessIntent | None
    entities: BusinessEntities
    clarification_question: str | None
~~~

其中 `BusinessEntities` 是全局统一对象，包含 16 个可空字符串字段：

- `operation_plan_no`
- `train_no`
- `formation_no`
- `contract_no`
- `document_type`
- `document_no`
- `customer`
- `supplier`
- `coal_type`
- `departure_station`
- `arrival_station`
- `railway_section`
- `time_range`
- `data_version`
- `metric_name`
- `exception_description`

这些实体进入 `ChatState.business_understanding` 并被 checkpoint 保存，但当前业务节点尚未消费它们。现阶段的直接用途主要是结构化输出约束和离线/Langfuse 评测。

## 4. 当前评测现状

项目目前有 26 条 Business Understanding 业务理解用例，并通过 Langfuse Dataset Experiment 运行 live model。当前五个确定性分数为：

- `route_accuracy`
- `intent_accuracy`
- `key_entity_recall`
- `clarification_accuracy`
- `schema_validity`

其中 `key_entity_recall` 对标注中列出的实体做字段名和值的精确比较。因此，用例对实体的错误理解会直接把合理模型输出判错；入口分类、实体提取和业务参数澄清目前也被放在同一份 Dataset 中评测。

相关文件：

- `backend/tests/fixtures/business_understanding_cases.json`
- `backend/app/domains/chat/graph/business_understanding/evaluation.py`
- `backend/app/evaluation/business_understanding_langfuse.py`

## 5. 触发本次讨论的具体失败样例

Langfuse trace：`trace-551036cf51d687b5f052cd32ddeed02f.json`。

对话内容：

~~~text
用户：查神木站和榆林站本月模拟装车计划
助手：开发阶段暂不执行业务查询
用户：按实际版呢
~~~

Dataset 当前期望：

~~~json
{
  "route": "CLARIFY",
  "intent": "BUSINESS_DATA_QUERY",
  "key_entities": {
    "time_range": "本月",
    "metric_name": "装车计划",
    "data_version": "实际版"
  },
  "clarification_contains": "神木站还是榆林站"
}
~~~

模型实际输出：

~~~json
{
  "route": "BUSINESS",
  "intent": "BUSINESS_DATA_QUERY",
  "entities": {
    "departure_station": "神木站,榆林站",
    "time_range": "本月",
    "data_version": "实际版",
    "metric_name": "装车计划"
  },
  "clarification_question": null
}
~~~

本次评测因此得到 `route_accuracy=0`、`clarification_accuracy=0`，其他三个维度为 1。

当前讨论的判断是：模型的业务语义判断更合理，Dataset 期望有问题。用户明确使用“神木站和榆林站”，表达的是并列查询集合，而不是无法确定的候选项；“按实际版呢”只修改数据版本，应该继承两个站点、时间范围和指标。

如果下游接口支持多站点，应一次查询；如果接口一次只支持一个站点，系统也可以拆成两次调用并汇总。只有业务规则明确禁止多站点，且系统无法安全选择执行策略时，才应向用户说明限制并澄清。接口能力或业务约束尚未确定时，入口分类器不应擅自把明确的多值诉求改写成单选问题。

这个样例同时暴露出当前 Schema 的问题：`departure_station` 是 `str | None`，无法规范表示多个站点，模型只能生成 `"神木站,榆林站"`。逗号、顿号、空格等序列化差异会进一步造成脆弱的精确匹配。

## 6. 已识别的主要问题

### 6.1 实体提取发生得过早

在尚未进入具体业务流程、尚未选择实际接口或工具之前，入口节点并不知道：

- 哪些参数是该能力真正需要的；
- 哪些参数可选、哪些必填；
- 参数是否允许多个值；
- 缺失参数能否通过用户身份、默认配置或上下文补全；
- 接口一次支持多个条件，还是需要 fan-out 多次调用；
- 哪些表达只是检索文本，不需要结构化为实体。

因此，入口节点无法可靠判断“是否缺少执行所必需的信息”。

### 6.2 `BusinessEntities` 正在演变为超级对象

铁路计划、列车、编组、合同、客户、煤种、车站、单据、时间、版本、指标和异常被放在同一个全局对象中。随着业务能力增加，所有新场景都需要继续增加可空字段，并同步扩大：

- Pydantic Schema；
- 入口 Prompt；
- Few-shot；
- checkpoint 序列化类型；
- 测试 fixture；
- Langfuse Dataset 期望；
- 实体召回评分逻辑。

全局对象会逐渐失去明确消费者和不变量。

### 6.3 入口澄清与业务参数澄清混在一起

当前 `CLARIFY` 同时可能表示：

1. route 或 intent 本身无法确定；
2. intent 已确定，但具体业务执行参数不足。

例如“这个计划有问题”可能属于入口意图不清；而“查一下我的运单”已经可以确定为 `BUSINESS_DATA_QUERY`，缺少运单号是数据查询流程的问题。

当前 `clarify_node` 恢复后固定回到 `business_understanding`，无法自然地返回触发澄清的具体业务子流程。

### 6.4 `metric_name` 的语义过宽

当前 `metric_name` 同时承载：

- 真正的统计指标，如装车数量、完成率；
- 状态查询，如到站状态、运单状态；
- 计划对象，如运行计划、编组计划；
- 专业概念，如发热量、重车周转时间；
- 规则主题，如热值扣罚。

这些内容没有统一的数据类型和统一消费者。若采用能力/工具局部 Schema，很多 `metric_name` 实际会自然转化为“选择哪个能力或工具”，无需保留一个全局字段。

### 6.5 当前满分或失败可能评价了错误契约

确定性评测可以证明实现符合人工标注，但不能证明标注符合真实业务能力。双站点样例说明，错误的期望会让合理模型输出失分，并诱导后续 Prompt 朝过度澄清方向优化。

## 7. know-engine 对照结论

已检查参考仓库：

~~~text
C:\dev\workspace\LLMentor-master-0161c1d4ab31ed531d35b3f6d3ecf4b2d000dff0\know-engine
~~~

know-engine 也没有独立的实体识别节点。它在 `IntentRecognitionService` 的同一次模型调用中生成：

~~~text
reasoning + related + intent + entities
~~~

全局 `Entities` 包含 8 个汽车字段：`car_model`、`car_id`、`order_id`、`dealer`、`fault_description`、`appointment_time`、`part_name`、`function_name`。

关键文件：

- `know-engine/src/main/resources/prompts/intent-recognition-new-prompt.txt`
- `know-engine/src/main/java/cn/hollis/llm/mentor/know/engine/ai/model/IntentRecognitionResult.java`
- `know-engine/src/main/java/cn/hollis/llm/mentor/know/engine/ai/service/IntentRecognitionService.java`
- `know-engine/src/main/java/cn/hollis/llm/mentor/know/engine/chat/service/ChatApplicationService.java`

但生产链路中只有 `car_id` 被直接用于车辆归属和权限判断；`car_id`、`car_model` 的缺失选择逻辑已经被注释，其他多数结构化实体没有发现直接消费者。后续 `KnowEngineQueryTransformer` 又会独立结合历史改写查询并标准化车型信息，而不是复用入口 `car_model`。

因此，know-engine 证明了“入口同时提取实体”是当前参考实现的做法，但不能证明这种职责划分适合扩展后的铁路和煤炭场景。汽车场景只有 8 个字段时问题不突出；迁移到更多业务对象后，全局模型迅速膨胀。

## 8. 候选方案比较

### 方案 A：维持当前入口统一提取

优点：

- 一次 LLM 调用即可获得分类和参数；
- 实现简单，现有测试和 checkpoint 无需迁移；
- 少量、稳定、且被所有流程共同消费的实体场景可以工作。

问题：

- 入口必须知道所有下游能力的参数契约；
- 超级对象继续膨胀；
- 容易过度澄清；
- 多值、互斥字段和能力特有校验难以表达；
- 目前大量字段没有消费者。

### 方案 B：增加独立的全局实体识别节点

流程变成 `business_understanding → global_entity_extraction → business flow`。

它可以缩小入口 Prompt，但没有解决实体所有权和超级对象问题，只是把问题移动到另一个节点。除非系统确实存在一套稳定、跨所有业务能力共享的领域本体，否则不建议作为目标架构。

### 方案 C：按业务子流程维护专属实体 Schema

入口只输出 route 和 intent；进入 `BUSINESS_DATA_QUERY`、知识问答或其他业务子图后，各流程提取自己的参数。

该方案能建立更清晰的职责，但如果每个 intent 内仍然包含大量不同工具，intent 级 Schema 仍可能再次变成局部超级对象。

### 方案 D：实体识别下沉为能力/工具参数生成

入口只负责选择业务方向；具体流程先选择能力或工具，然后依据该工具的类型化参数 Schema 生成参数并校验。

例如：

~~~python
class LoadingPlanQuery(BaseModel):
    stations: list[str]
    time_range: str
    data_version: Literal["实际版", "模拟版"]

class DocumentStatusQuery(BaseModel):
    document_type: DocumentType
    document_numbers: list[str]
~~~

或者直接让这些模型成为工具参数：

~~~python
get_loading_plan(
    stations: list[str],
    time_range: str,
    data_version: str,
)
~~~

这时“实体识别”不再是一个顶层通用步骤，而是将自然语言转换为选定业务能力的合法调用参数。当前讨论倾向方案 D，知识/RAG 流程则按需要维护自己的 `RetrievalQuery`，而不是强制提取统一实体。

方案 D 仍需高级模型评估：是否应由一个 planner 同时选择工具并生成参数，还是先选择能力、再由专门节点生成参数；以及怎样避免工具数量增多后 planner Prompt 重新膨胀。

## 9. 候选目标 Graph

当前倾向的父图：

~~~text
START
  ↓
business_understanding
  │
  ├─ NON_BUSINESS ───────────────→ general_llm → END
  │
  ├─ route/intent 不明确 ────────→ route_clarify
  │                                   ↓ resume
  │                              business_understanding
  │
  └─ BUSINESS
        ↓ intent 确定性分发
        ├─ POLICY_RULE_QA ─────────→ policy_rag_flow
        ├─ TRANSPORT_OPERATION_QA ─→ transport_rag_flow
        ├─ COAL_SALES_QA ──────────→ coal_sales_flow
        ├─ PROFESSIONAL_KNOWLEDGE_QA → knowledge_rag_flow
        ├─ BUSINESS_DATA_QUERY ─────→ data_query_flow
        └─ OTHER_BUSINESS ──────────→ other_business_flow
~~~

`data_query_flow` 候选结构：

~~~text
data_query_plan
  ↓ 选择查询能力/工具并生成类型化参数
validate_query_request
  ├─ 参数缺失或真正歧义
  │       ↓
  │  data_query_clarify
  │       ↓ resume
  │  data_query_plan / validate_query_request
  │
  └─ 参数完整
          ↓
     execute_query
       ├─ 接口支持多值：单次调用
       └─ 接口只支持单值：多次调用/fan-out
          ↓
     aggregate_results
          ↓
     answer → END
~~~

父级 `ChatState` 建议只保留 messages 和精简后的业务决策；数据查询参数、工具结果和局部澄清上下文尽量保存在子图 State 中，避免父级状态演变成另一个超级对象。

## 10. 多值、歧义与澄清语义

后续需要在契约中明确区分：

- “神木站和榆林站”：明确集合，通常不是歧义；
- “神木站还是榆林站，我记不清了”：明确表达不确定，属于真正歧义；
- “查这两个站”：需要结合历史解析集合；
- “按实际版呢”：修改版本，继承历史中已经明确的完整对象集合；
- 接口一次只接受一个站：执行策略约束，不等于用户意图不明确；
- 业务规则只允许单站对比之外的某种查询：此时才可能需要业务流程澄清。

是否需要澄清应由“用户语义是否明确 + 已选择能力的参数契约 + 接口/业务能力”共同决定，不能只由模型能力或全局 Prompt 决定。

## 11. 澄清节点的候选设计

当前 `clarify_node` 总是恢复到 `business_understanding`。候选方式有两种：

1. 父图和各子图拥有各自的澄清节点。子图内 interrupt 后恢复到本流程，状态边界最清晰；
2. 维护通用 `ClarificationRequest(question, resume_target)`，由固定枚举映射到允许的恢复节点，避免任意动态跳转。

需要高级模型判断哪一种更符合 LangGraph checkpoint/subgraph interrupt 的实践。无论采用哪种方式，都不建议所有业务参数补充再次经过完整入口分类。

## 12. 评测体系的候选拆分

入口业务理解 Dataset：

- `route_accuracy`
- `intent_accuracy`
- 入口级澄清准确率
- 路由输出 Schema 合法性

具体业务能力 Dataset：

- 能力/工具选择准确率；
- 工具参数准确率；
- 多值参数准确率；
- 必要参数完整性；
- 参数澄清准确率；
- 工具执行和结果聚合正确性。

双站点样例更适合作为数据查询能力的多值参数用例。入口只需验证它被识别为 `BUSINESS + BUSINESS_DATA_QUERY`，不应在尚不知道接口契约时要求入口决定是否拆分调用。

## 13. 迁移风险和兼容性考虑

### 13.1 已持久化 checkpoint

当前 PostgreSQL checkpoint 会保存 `BusinessUnderstandingResult`、`BusinessEntities`、`BusinessRoute` 和 `BusinessIntent` 的精确类型，项目对 JsonPlus serializer 还有反序列化白名单和往返测试。直接删除或改变这些类型可能导致旧会话无法恢复。

需要在实施前决定：

- 是否保留 legacy 类型仅用于旧 checkpoint 读取；
- 是否给 Graph State 和业务理解结果增加版本；
- 是否迁移/清理开发期 checkpoint；
- 是否允许旧会话按旧图恢复，新会话进入新图；
- 节点名和 interrupt payload 改动是否影响待恢复会话。

### 13.2 SSE 和固定业务边界

当前 SSE 投影、运行时和测试显式识别 `business_boundary` 节点及其固定消息。替换成真实业务子图时需要同步调整事件投影，不能只改 Graph builder。

### 13.3 Prompt 与 Dataset 耦合

当前 Prompt、Pydantic Schema、26 条本地 fixture、Langfuse Dataset 和五维 scorer 互相耦合。职责拆分后应分层迁移评测，不宜继续用同一份期望同时验证路由和所有工具参数。

### 13.4 业务接口尚未确定

目前还没有真实查询接口契约。过早确定所有工具参数模型，可能只是把推测从 `BusinessEntities` 搬到一组未经验证的 Schema。推荐先从已确认的真实接口或最小查询能力开始，再扩展工具集合。

## 14. 建议高级模型重点挑战的假设

1. `route + intent` 是否真的应该一次模型调用完成，还是入口只判断 BUSINESS/NON_BUSINESS，再由业务子图细分？
2. 六个现有 intent 是否足以稳定决定不同执行流程，还是它们只是回答 Prompt 分类，不适合作为 Graph 分支？
3. 对 RAG 知识问答，是否完全不需要结构化实体，还是需要局部的检索过滤模型？
4. 数据查询应采用“先选工具再填参数”，还是直接进行 constrained tool calling？
5. 当工具很多时，如何避免工具选择 Prompt 成为新的超级 Prompt？
6. 多值接口应由单个工具接受列表，还是由 Graph 使用 fan-out/`Send` 并行执行？
7. 通用澄清节点与子图局部澄清节点，哪一种更容易保证 checkpoint 恢复正确性？
8. 是否应把 `CLARIFY` 从 `BusinessRoute` 中移出，改成独立的 next action/readiness 状态？
9. 如何定义旧 checkpoint 的兼容策略，避免模型/Schema 升级破坏正在等待用户回复的 interrupt？
10. 在真实业务接口尚未确定时，最小且可逆的第一步应该是什么？

## 15. 此前非结论

> 本节记录本文首次形成时尚未决定的事项。后续讨论已经收敛出新的明确判断；如本节与第 17 节冲突，以第 17 节为准。

首次形成本文时，以下内容均不是既定决定：

- 尚未决定删除 `BusinessEntities`；
- 尚未决定移除 `CLARIFY` route；
- 尚未决定为每个 intent 建立独立子图；
- 尚未决定具体工具和参数 Schema；
- 尚未修改双站点 Dataset 用例；
- 尚未修改 Langfuse Dataset；
- 尚未修改生产 Prompt、Graph、checkpoint 或 SSE；
- 尚未选择旧 checkpoint 的迁移方式。

当时较强的阶段性判断只有两点：

1. 用户明确表达多个对象时，不应仅因为出现多个值就自动澄清为单选；
2. 将所有领域实体长期集中在入口 `BusinessEntities` 中，缺少清晰消费者和能力契约，不适合作为可持续扩展方向。

## 16. 相关资料索引

项目内：

- `docs/my-specs/项目中意图识别提示词的优化.md`
- `docs/my-specs/ke-engine架构讨论过程与阶段性结论.md`
- `backend/app/domains/chat/graph/builder.py`
- `backend/app/domains/chat/graph/state.py`
- `backend/app/domains/chat/graph/business_understanding/models.py`
- `backend/app/domains/chat/graph/business_understanding/prompt.py`
- `backend/app/domains/chat/graph/nodes/business_understanding.py`
- `backend/app/domains/chat/graph/nodes/clarify.py`
- `backend/tests/fixtures/business_understanding_cases.json`
- `backend/app/domains/chat/graph/business_understanding/evaluation.py`
- `backend/app/evaluation/business_understanding_langfuse.py`

外部参考仓库：

- `C:/dev/workspace/LLMentor-master-0161c1d4ab31ed531d35b3f6d3ecf4b2d000dff0/know-engine/src/main/resources/prompts/intent-recognition-new-prompt.txt`
- `C:/dev/workspace/LLMentor-master-0161c1d4ab31ed531d35b3f6d3ecf4b2d000dff0/know-engine/src/main/java/cn/hollis/llm/mentor/know/engine/ai/model/IntentRecognitionResult.java`
- `C:/dev/workspace/LLMentor-master-0161c1d4ab31ed531d35b3f6d3ecf4b2d000dff0/know-engine/src/main/java/cn/hollis/llm/mentor/know/engine/chat/service/ChatApplicationService.java`
- `C:/dev/workspace/LLMentor-master-0161c1d4ab31ed531d35b3f6d3ecf4b2d000dff0/know-engine/src/main/java/cn/hollis/llm/mentor/know/engine/rag/modules/KnowEngineQueryTransformer.java`

本地 trace：

- `C:/Users/83649/Downloads/trace-551036cf51d687b5f052cd32ddeed02f.json`

## 17. 后续讨论形成的最终判断

在完成 `add-business-understanding` 和 `add-langfuse-observability`、同步主规格并归档两个 OpenSpec change 后，讨论进一步收敛。当前决定不再选择“把实体识别迁移到独立节点、业务子图或工具参数生成节点”的表达方式，而是直接从 Business Understanding 中删除实体识别职责。

### 17.1 不再维护显式实体识别能力

当前明确决定：

- 删除全局 `BusinessEntities`；
- 删除 `BusinessUnderstandingResult.entities`；
- 删除 Business Understanding Prompt 中的实体白名单、实体提取规则和实体 Few-shot；
- 不增加独立实体识别节点；
- 不为每个 intent 额外维护所谓“实体识别 Schema”；
- 不再把 Agent 调用工具时生成参数称为实体识别。

Agent 根据工具参数 Schema 生成调用参数属于正常 Tool Calling。工具或领域服务继续负责参数类型校验、名称规范化、对象存在性、业务约束和数据权限，但这些能力不需要在入口抽象为一套统一实体模型。

Business Understanding 的目标输出收敛为：

~~~python
class BusinessUnderstandingResult(BaseModel):
    reasoning: str
    route: BusinessRoute
    intent: BusinessIntent | None
    clarification_question: str | None
~~~

### 17.2 Business Understanding 的保留职责

入口只负责：

1. 结合完整会话历史理解当前问题；
2. 判断请求属于 `BUSINESS`、`NON_BUSINESS` 还是需要入口澄清；
3. 从固定业务意图中选择主要 `intent`；
4. 在业务范围或意图本身无法确定时生成最小澄清问题。

入口不再负责：

- 提取合同号、站点、时间范围、版本、指标等结构化实体；
- 判断具体工具有哪些必填参数；
- 因缺少运单号、合同号、时间或站点而提前澄清；
- 决定多值条件应单次查询还是 fan-out 执行。

例如“查一下我的运单”可以直接识别为 `BUSINESS + BUSINESS_DATA_QUERY`。缺少运单号是否影响执行，应由后续 Agent 在选定工具后判断，而不是由入口返回 `CLARIFY`。

### 17.3 intent 用于装配 Business Knowledge Agent

后续 Business Knowledge Agent 根据入口 `intent` 选择主要 Agent Profile，并注入不同的 Prompt、Skills 和 Tools：

~~~text
Business Understanding
  ↓ route + intent
Agent Profile Resolver
  ↓ 注入 Prompt + Skills + Tools
Business Knowledge Agent
  ↓ Tool Calling / request_human_input / Evidence Validation
Grounded Business Answer
~~~

intent 决定主要能力配置，但不同 Profile 可以共享工具。最终可用工具还必须与当前业务系统来源、用户角色和数据权限取交集，不能只依赖模型自行遵守权限描述。

### 17.4 澄清职责分层

`CLARIFY` 暂时保留在入口协议中，但语义收窄为“业务范围或 intent 无法确定”。

后续 Agent 已经确定具体能力或工具后，如果缺少执行必需参数，应通过 `request_human_input` 在 Agent 执行上下文中触发 interrupt/resume。参数补充不再返回 Business Understanding 重新分类。

### 17.5 评测体系同步精简

Business Understanding 评测删除：

- Dataset 中的 `key_entities`；
- `key_entity_recall` scorer；
- 实体字段集合、实体序列化和实体提取 Prompt 测试。

入口只保留四类评测：

- `route_accuracy`；
- `intent_accuracy`；
- `clarification_accuracy`；
- `schema_validity`。

工具选择、工具参数、多值参数、参数澄清和证据充分性在 Business Knowledge Agent 接入后建立独立评测，不再与入口 Dataset 混合。双站点样例在入口只验证 `BUSINESS + BUSINESS_DATA_QUERY`，不再评测站点实体值。

### 17.6 变更范围与兼容策略

删除实体识别先作为一个独立且较小的 OpenSpec change 实施，不与 Business Knowledge Agent 建设绑定。建议 change 名称为：

~~~text
remove-business-entity-extraction
~~~

该 change 只修改 Business Understanding 的模型、Prompt、Dataset、scorer、测试和对应主规格；当前 `BUSINESS -> business_boundary` 拓扑可以继续保留。Business Knowledge Agent、intent Profile、Skills、Tools 和 Evidence Validation 以后通过独立 change 接入。

当前明确不考虑旧数据或旧 checkpoint 兼容：

- 不保留 legacy `BusinessEntities` 类型；
- 不设计双写、State 版本或旧节点兼容周期；
- 可以直接删除旧 Schema 和相关序列化测试；
- 部署或开发切换前允许清理现有 LangGraph checkpoint；
- 旧会话不保证恢复。

这是一项有意的 breaking state/schema change，应在新 OpenSpec proposal 中明确记录，但不需要为旧数据设计迁移方案。
