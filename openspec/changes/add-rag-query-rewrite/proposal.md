## Why

RAG 查询链路需要先将依赖会话上下文、包含口语噪声或术语不规范的用户问题转换为一条可独立理解且适合检索的查询。先实现可独立运行的 Query Rewrite 最小切片，可以在 Router 和 Retriever 尚未实现前，用真实模型与评测样例验证改写质量、上下文边界和延迟。

## What Changes

- 新增 RAG domain 内的一对一 Query Rewrite 能力，将原始问题、可选会话上下文和可选业务上下文转换为单个 `standalone_query`。
- 采用“受约束的检索化改写”：补全上下文、压缩口语表达并规范术语，同时保留实体、时间、数值、范围、否定、比较和归属等硬约束。
- 新增完整 RAG Graph 的首个增量，当前拓扑为 `START -> query_rewrite -> END`；顶层 state、builder 和 Studio 入口保持管线级命名，后续阶段直接扩展同一 Graph。
- Rewrite 失败时不重试，直接使用 `original_query` 作为 `standalone_query` 继续当前 RAG Graph，不增加状态、失败码或 warning 字段。
- 新增节点契约测试、Prompt/模型集成测试入口和面向真实模型的 Query Rewrite 评测样例。
- 接入现有 Langfuse callback 传递方式，观察节点、模型调用和实际查询。
- 本 change 不实现 Query Router、Content Retriever、MCP Endpoint、EvidencePackage 或完整 RAG 管线。

## Capabilities

### New Capabilities

- `rag-query-rewrite`: 定义 Query Rewrite 的输入输出、受约束检索化规则、上下文边界、LangGraph 最小切片、失败降级、观测和评测要求。

### Modified Capabilities

无。

## Impact

- 影响 `backend/app/domains/rag/graph/`，该目录将新增 Query Rewrite 的阶段模型、Prompt、node、state、builder 和测试边界；本 change 不新增独立 Query Rewrite service。
- 复用项目现有 LangChain、LangGraph、模型初始化和 Langfuse callback 能力，不新增外部服务。
- 不修改现有 Chat Graph、Business Understanding、Document 入库链路及其持久化模型。
- 不新增对外 HTTP/MCP API；最小切片通过测试和开发期调用入口验证。
