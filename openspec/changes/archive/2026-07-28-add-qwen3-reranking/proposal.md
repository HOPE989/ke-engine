## Why

当前 `DOCUMENT_HYBRID` 在父分段替换后仅使用应用层 RRF 排序，最终顺序仍主要取决于 BM25 与向量召回名次，缺少对“候选父分段能否回答当前问题”的精细判断。接入百炼 `qwen3-rerank`，可以在保持现有父分段检索语义的同时，对 RRF 候选执行精排序和低相关结果过滤。

## What Changes

- 保持 BM25 与 KNN 每路最多召回 10 条，并继续在各通道中先将命中子分段替换为完整父分段、按父分段稳定去重。
- 将应用层 RRF 的输出预算明确为 10 条，再把这 10 条父分段一次性提交给百炼 `qwen3-rerank`。
- 使用百炼返回的 `relevance_score` 重新排序，过滤分数低于 `0.6` 的候选，最终最多返回 5 条；全部候选低于阈值时返回正常的空检索结果。
- 为最终文档候选保留 rerank 分数，并在诊断中记录各阶段的有界文本预览，以及 Rerank 排名、分数、耗时和百炼请求 ID。
- 复用现有 `OPENAI_API_KEY` 和指向百炼 Workspace 的 `OPENAI_BASE_URL`，不新增或重写 Bailian/DashScope 凭证配置；复用项目已有的异步 `httpx` 依赖调用专用 Rerank API。
- 将模型、Q&A 指令、RRF Top 10、`0.6` 阈值和最终 Top 5 作为固定策略，不增加新的环境变量或检索配置项。
- 百炼调用失败时沿用现有 `FAILED` 结果，不重试、不探测其他端点，也不回退到未精排的 RRF 结果。
- 增加覆盖正常精排、阈值过滤、空结果和调用失败的离线测试，不在默认测试中访问百炼。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `rag-hybrid-document-retrieval`: 在现有父分段替换与应用层 RRF 之后增加百炼 Qwen3 精排、`0.6` 阈值过滤、Top 5 截断、分数输出、诊断及失败行为。

## Impact

- 影响 `backend/app/infrastructure/elasticsearch.py` 及 RAG 基础设施装配，在现有 Hybrid Retriever 的 RRF 后增加异步百炼 Rerank 调用。
- 影响 `DocumentCandidate` 和检索诊断契约，为最终父分段保留 Rerank 分数。
- 影响 `backend/app/entrypoints/rag_studio.py`，在进程装配时复用现有百炼凭证和 Workspace Base URL 创建共享异步 Rerank 客户端。
- 影响 Hybrid Retriever、Graph node、配置装配及 RAG Studio 的离线测试。
- 新增对百炼 `qwen3-rerank` 服务可用性和调用配额的运行时依赖；不新增 Python 包、不修改 Elasticsearch 索引、不改变父子分段结构，也不新增对外 HTTP API。
