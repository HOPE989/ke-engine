# 清理 Agent/Chat 占位模块设计

## 背景

当前项目只有 Document 领域完成了可运行的业务开发。`contracts/agent`、`domains/agent`、`services/agent_api` 及其入口和测试主要来自早期单轮 Chat Demo 与目标架构占位，不代表后续真正的 RAG Chat 或 Agent 设计。

后续计划先独立开发常规 RAG Chat，再开发具备工具调用、规划和任务编排能力的 Agent。继续保留当前占位会造成模块命名、架构测试和 OpenSpec 现状与真实开发阶段不一致，因此本次先彻底清理相关运行链路。

## 目标

- 删除当前 Agent/Chat 占位代码及其直接引用。
- 保持 Document API、Document Worker、Celery、数据库迁移及文档处理能力不变。
- 保留 Document 正在使用的 OpenAI 配置、LangChain 依赖、Embedding 和图片描述能力。
- 让项目结构和架构测试准确表达“当前只有 Document 领域完成开发”。
- 将现有门户身份接入提案收缩为只在 Document API 走通 Mock 身份链路。
- 为未来从零设计 RAG Chat 和 Agent 留出干净边界。

## 非目标

- 不实现 RAG Chat。
- 不创建新的 Chat 或 Agent 目录骨架。
- 不重构 Document 领域。
- 不删除 Document 使用的通用 LLM 配置和依赖。
- 不修改已归档的历史 OpenSpec change 和历史设计文档。
- 不在本次清理中实现门户身份 Middleware。

## 删除范围

### Agent/Chat 运行代码

- `backend/app/contracts/agent/`
- `backend/app/domains/agent/`
- `backend/app/services/agent_api/`
- `backend/app/entrypoints/agent_api.py`
- `backend/app/infrastructure/llm.py`

`infrastructure/llm.py` 仅重新导出 `domains.agent.services.chat.get_chat_model`，Agent 域删除后没有独立价值。

### Agent/Chat 测试

删除只验证单轮 Chat Demo、Agent 目录结构或 Agent API 的测试，包括：

- `test_agent_domain_layout.py`
- `test_chat_api.py`
- `test_chat_llm_integration.py`
- `test_chat_module.py`
- `test_chat_router.py`
- `test_chat_service.py`
- `test_chat_settings.py`

同时从共享测试中删除 Agent API、Agent contracts 和 Agent domain 的断言，保留并继续验证 Document 相关行为。

### 开发命令与现行规格

- 从根 Makefile 删除 `AGENT_API_PORT`、`dev-agent-api` 及 `dev-all` 对 Agent API 的启动依赖。
- 删除当前主规格 `openspec/specs/chat-demo/spec.md`，因为系统不再提供该能力。
- 保留 `openspec/changes/archive/2026-06-29-add-chat-demo/` 和历史 Chat Demo 设计文档，作为历史记录。

### 身份与密码占位

- 删除 `backend/app/contracts/identity/` 中未使用的占位契约。
- 删除 `backend/app/core/security.py`、`password_hash_iterations` 及只验证密码哈希占位的测试。

这些内容将在门户身份接入变更中由新的请求级 Principal 和 Mock 身份链路替代，不属于现有 Document 能力。

## 保留范围

以下能力必须完整保留：

- `backend/app/domains/document/`
- `backend/app/services/document_api/`
- `backend/app/entrypoints/document_api.py`
- `backend/app/entrypoints/document_worker.py`
- `backend/app/entrypoints/celery_worker.py`
- Document 的数据库模型、迁移、对象存储、Kafka、Redis、Elasticsearch 与 Celery 能力
- `openai_api_key`、`openai_base_url`、`openai_model` 配置
- `langchain-openai` 依赖
- `OpenAIEmbeddings` 文档向量化
- Document Worker 和 Celery 使用的 `ChatOpenAI` 图片描述能力
- 所有 Document 专属测试

## OpenSpec 调整

当前未实施的 `add-portal-identity-mock-chain` 仍然有效，但其目标服务从“Agent API 和 Document API”收缩为“Document API”。需要同步修改：

- `proposal.md` 中的影响范围和服务装配描述；
- `design.md` 中的当前状态、注册决策和迁移步骤；
- `portal-identity-consumption/spec.md` 中的双 API 要求与 Agent API 场景；
- `tasks.md` 中的双服务装配任务。

Mock Principal、IdentityMiddleware、Dependency、无 Settings 和不接真实门户等核心设计保持不变。

## 实施顺序

1. 先调整测试，使目标架构只要求 Document 运行链路，并增加 Agent/Chat 运行模块不存在的断言。
2. 删除 Agent/Chat 专属测试和运行代码。
3. 清理共享测试、Makefile、`conftest.py` 和其他直接引用。
4. 删除身份与密码占位。
5. 删除现行 `chat-demo` 主规格并同步收缩门户身份提案。
6. 全仓搜索残留运行时导入和启动命令。
7. 运行 OpenSpec 严格校验和完整后端测试。

## 验证标准

- 仓库不存在 `app.contracts.agent`、`app.domains.agent`、`app.services.agent_api` 和 `app.entrypoints.agent_api` 的运行时导入。
- 根 Makefile 不再暴露或启动 Agent API。
- 当前主 OpenSpec 不再声明系统提供 Chat Demo。
- 门户身份接入提案只要求 Document API 装配 Mock 身份链路。
- Document API 健康检查、文档处理、向量化、Worker 和 Celery 相关测试继续通过。
- 完整后端测试套件通过。

## 风险与控制

- 删除 `chat-demo` 会移除当前单轮聊天入口；这是本次清理的明确目标，未来由新的 RAG Chat 变更重新定义。
- OpenAI 配置同时被旧 Chat Demo 和 Document 使用，因此只删除 Agent 侧调用代码，不删除配置或依赖。
- 共享架构测试混合了 Document 与 Agent 断言，修改时只移除 Agent 部分，不能削弱 Document 架构约束。
- 当前门户身份提案尚未实施且未提交，可以直接收缩制品，不需要应用代码迁移。
