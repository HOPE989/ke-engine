# Agent/Chat Placeholder Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除当前 Agent/Chat 与身份密码占位，使仓库准确表达“当前只完整开发了 Document”，同时保持全部 Document 能力可用。

**Architecture:** 通过架构测试先声明 Agent/Chat 运行模块不存在，再删除对应 contracts、domain、service、entrypoint、测试与启动命令。主 OpenSpec 删除已下线的 `chat-demo` 能力，未实施的门户身份提案收缩为只装配 Document API；Document 使用的 OpenAI 配置、LangChain 依赖、Embedding 与图片描述链路保持不变。

**Tech Stack:** Python 3.11、FastAPI、pytest、OpenSpec、GNU Make、Git

## Global Constraints

- 不修改 `backend/app/domains/document/`、`backend/app/services/document_api/`、Document Worker、Celery 或数据库迁移。
- 保留 `openai_api_key`、`openai_base_url`、`openai_model`、`langchain-openai`、`OpenAIEmbeddings` 和 Document 图片描述能力。
- 不创建新的 Chat 或 Agent 骨架，不实现 RAG Chat。
- 保留 `openspec/changes/archive/2026-06-29-add-chat-demo/` 和历史设计文档。
- 当前门户身份提案只面向 Document API，仍保持默认 Mock、无 Settings、不接真实门户。

---

### Task 1: 删除 Agent/Chat 运行模块与专属测试

**Files:**
- Modify: `backend/tests/test_project_layout.py`
- Modify: `backend/tests/test_target_architecture_layout.py`
- Modify: `backend/tests/test_service_entrypoints.py`
- Modify: `backend/tests/test_document_resource_ownership.py`
- Modify: `backend/tests/conftest.py`
- Delete: `backend/app/contracts/agent/`
- Delete: `backend/app/domains/agent/`
- Delete: `backend/app/services/agent_api/`
- Delete: `backend/app/entrypoints/agent_api.py`
- Delete: `backend/app/infrastructure/llm.py`
- Delete: `backend/tests/test_agent_domain_layout.py`
- Delete: `backend/tests/test_chat_api.py`
- Delete: `backend/tests/test_chat_llm_integration.py`
- Delete: `backend/tests/test_chat_module.py`
- Delete: `backend/tests/test_chat_router.py`
- Delete: `backend/tests/test_chat_service.py`
- Delete: `backend/tests/test_chat_settings.py`

**Interfaces:**
- Consumes: 现有 Document API、Document Worker 和 Celery 公共入口。
- Produces: 不再包含任何可导入 Agent/Chat 运行模块的后端结构；pytest 公共 fixture 只清理 Settings 缓存。

- [ ] **Step 1: 先把项目布局测试改为要求 Agent/Chat 模块不存在**

在 `test_project_is_split_into_backend_and_frontend` 中保留 Document 断言并加入：

```python
assert not (root / "backend" / "app" / "entrypoints" / "agent_api.py").exists()
assert not (root / "backend" / "app" / "services" / "agent_api").exists()
assert not (root / "backend" / "app" / "domains" / "agent").exists()
assert not (root / "backend" / "app" / "contracts" / "agent").exists()
```

从 `test_target_architecture_files_exist` 的 `expected_files` 删除所有 `entrypoints/agent_api.py`、`services/agent_api/*`、`domains/agent/*`、`contracts/agent/*` 和 `infrastructure/llm.py` 条目；在同一测试末尾加入：

```python
for removed_path in [
    "entrypoints/agent_api.py",
    "services/agent_api",
    "domains/agent",
    "contracts/agent",
    "infrastructure/llm.py",
]:
    assert not (app_root / removed_path).exists()
```

- [ ] **Step 2: 运行布局测试并确认它因现有占位目录仍存在而失败**

Run:

```powershell
Set-Location backend
uv run pytest tests/test_project_layout.py tests/test_target_architecture_layout.py -q
```

Expected: FAIL，失败信息指出 `agent_api.py`、`services/agent_api`、`domains/agent`、`contracts/agent` 或 `infrastructure/llm.py` 仍然存在。

- [ ] **Step 3: 删除 Agent/Chat 代码和专属测试**

使用 `apply_patch` 删除 Files 清单中的 Agent/Chat 目录、入口、`infrastructure/llm.py` 和七个专属测试文件。不得删除 `backend/app/domains/document` 下的任何文件。

- [ ] **Step 4: 清理共享测试和 pytest fixture 中的 Agent 引用**

把 `backend/tests/conftest.py` 改为：

```python
"""Shared pytest configuration."""

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def clear_cached_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```

把 `backend/tests/test_service_entrypoints.py` 改为只导入 `document_app` 并保留 `test_document_api_entrypoint_exposes_health_check`。从 `test_target_architecture_public_imports_are_available` 删除 Agent contracts、Agent domain、Agent service 和 Agent entrypoint 导入及断言；保留 Document、Celery 和 Document Worker 断言。

从 `test_contracts_are_grouped_by_domain_not_transport` 删除 `contracts/agent` 必须存在的断言，改为：

```python
assert (app_root / "contracts" / "document").is_dir()
assert not (app_root / "contracts" / "agent").exists()
```

从 `test_service_api_layers_do_not_keep_runtime_or_error_mapping_shells` 删除两条 `services/agent_api` 子文件断言。从 `backend/tests/test_document_resource_ownership.py` 删除完整的 `test_agent_api_app_does_not_own_document_deps` 测试函数。

- [ ] **Step 5: 运行定向测试并确认 Agent/Chat 清理通过**

Run:

```powershell
Set-Location backend
uv run pytest tests/test_project_layout.py tests/test_target_architecture_layout.py tests/test_service_entrypoints.py tests/test_document_resource_ownership.py -q
```

Expected: PASS，且测试收集阶段没有 `app.domains.agent` 或 `app.entrypoints.agent_api` 导入错误。

- [ ] **Step 6: 提交 Agent/Chat 运行模块清理**

```powershell
git add -- backend/app backend/tests
git commit -m "refactor: remove agent chat placeholders"
```

### Task 2: 删除 Agent API 开发命令

**Files:**
- Modify: `Makefile`
- Modify: `backend/tests/test_backend_makefile.py`

**Interfaces:**
- Consumes: `dev-document-api`、`dev-worker`、Celery 和基础设施 Make targets。
- Produces: `make dev` 只并行启动 Document API 与 Document Worker。

- [ ] **Step 1: 修改 Makefile 测试以拒绝 Agent API target**

在 `test_root_makefile_exposes_backend_dev_targets` 中将 Agent 相关正向断言替换为：

```python
assert "dev-agent-api:" not in content
assert "AGENT_API_PORT" not in content
assert "app.entrypoints.agent_api:app" not in content
assert "$(MAKE) -j 2 dev-document-api dev-worker" in content
```

继续保留对 `dev-document-api`、`dev-worker`、Kafka 和基础设施命令的全部原有断言。

- [ ] **Step 2: 运行测试并确认旧 Makefile 仍包含 Agent API 而失败**

Run:

```powershell
Set-Location backend
uv run pytest tests/test_backend_makefile.py::test_root_makefile_exposes_backend_dev_targets -q
```

Expected: FAIL，指出 `dev-agent-api:` 或 `AGENT_API_PORT` 仍在 Makefile 中。

- [ ] **Step 3: 从 Makefile 删除 Agent API 配置和命令**

删除：

```make
AGENT_API_PORT ?= 8001
```

从 `.PHONY` 和 `help` 删除 `dev-agent-api`，删除完整的 `dev-agent-api:` recipe，并把：

```make
dev:
	$(MAKE) -j 3 dev-document-api dev-agent-api dev-worker
```

改为：

```make
dev:
	$(MAKE) -j 2 dev-document-api dev-worker
```

- [ ] **Step 4: 运行 Makefile 测试**

Run:

```powershell
Set-Location backend
uv run pytest tests/test_backend_makefile.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交开发命令清理**

```powershell
git add -- Makefile backend/tests/test_backend_makefile.py
git commit -m "refactor: remove agent api dev target"
```

### Task 3: 删除身份和密码哈希占位

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/tests/test_target_architecture_layout.py`
- Delete: `backend/app/contracts/identity/`
- Delete: `backend/app/core/security.py`
- Delete: `backend/tests/test_security.py`

**Interfaces:**
- Consumes: 当前未实施的门户身份 OpenSpec；本任务不实现新的 Principal。
- Produces: 仓库不再暴露旧 `IdentityPrincipal(subject)` 或本地密码哈希 API。

- [ ] **Step 1: 增加身份和密码占位不存在的架构断言**

从 `test_target_architecture_files_exist` 的 `expected_files` 删除 `contracts/identity/http.py` 和 `core/security.py`，并加入：

```python
assert not (app_root / "contracts" / "identity").exists()
assert not (app_root / "core" / "security.py").exists()
```

从 `test_target_architecture_public_imports_are_available` 删除 `IdentityPrincipal` 导入与断言。从 `test_contracts_are_grouped_by_domain_not_transport` 删除 identity 目录必须存在的断言。

- [ ] **Step 2: 运行架构测试并确认占位仍存在而失败**

Run:

```powershell
Set-Location backend
uv run pytest tests/test_target_architecture_layout.py -q
```

Expected: FAIL，指出 `contracts/identity` 或 `core/security.py` 仍然存在。

- [ ] **Step 3: 删除占位文件与密码哈希配置**

使用 `apply_patch` 删除 `backend/app/contracts/identity/`、`backend/app/core/security.py` 和 `backend/tests/test_security.py`。从 `Settings` 删除：

```python
password_hash_iterations: int = 260_000
```

不得删除 `openai_api_key`、`openai_base_url` 或 `openai_model`。

- [ ] **Step 4: 运行配置与架构测试**

Run:

```powershell
Set-Location backend
uv run pytest tests/test_target_architecture_layout.py tests/test_document_config.py -q
```

Expected: PASS，且 Document OpenAI 配置测试继续通过。

- [ ] **Step 5: 提交身份与密码占位清理**

```powershell
git add -- backend/app/core/config.py backend/app/core/security.py backend/app/contracts/identity backend/tests/test_security.py backend/tests/test_target_architecture_layout.py
git commit -m "refactor: remove identity security placeholders"
```

### Task 4: 删除 Chat Demo 现行规格并收缩门户身份提案

**Files:**
- Delete: `openspec/specs/chat-demo/spec.md`
- Modify: `openspec/changes/add-portal-identity-mock-chain/proposal.md`
- Modify: `openspec/changes/add-portal-identity-mock-chain/design.md`
- Modify: `openspec/changes/add-portal-identity-mock-chain/specs/portal-identity-consumption/spec.md`
- Modify: `openspec/changes/add-portal-identity-mock-chain/tasks.md`

**Interfaces:**
- Consumes: 已确认的门户身份 Mock 链路设计。
- Produces: 只要求 Document API 装配身份链路的 apply-ready OpenSpec change。

- [ ] **Step 1: 删除现行 Chat Demo 主规格**

使用 `apply_patch` 删除 `openspec/specs/chat-demo/spec.md`。保留：

```text
openspec/changes/archive/2026-06-29-add-chat-demo/
docs/superpowers/specs/2026-06-29-chat-demo-design.md
```

- [ ] **Step 2: 将门户身份提案中的双 API 范围改为 Document API**

在 `proposal.md` 中把“两 API 服务共享身份链路”改为只在 Document API 注册。影响范围只列公共身份模块和 Document API 装配。

在 `design.md` 中明确当前唯一完整 API 服务是 Document API，并把注册决策和迁移步骤改为只修改 `backend/app/services/document_api/app.py`。

在 capability spec 中删除：

```markdown
#### Scenario: Agent API 消费 Mock 身份
```

把要求改为：

```markdown
### Requirement: Document API 消费公共身份链路
Document API SHALL 显式注册公共 IdentityMiddleware，并默认装配 Mock 身份提供器。

#### Scenario: Document API 消费 Mock 身份
- **WHEN** 受保护请求进入 Document API
- **THEN** Document API 路由能够通过公共 Dependency 取得 Mock Principal
```

健康检查场景只描述 Document API。

- [ ] **Step 3: 收缩门户身份任务清单**

将 tasks 中服务装配任务改为：

```markdown
- [ ] 3.1 增加服务装配失败测试，证明 Document API 注册公共身份链路且 `/health` 保持公开
- [ ] 3.2 在 Document API 的 `create_app()` 中显式注册 IdentityMiddleware 和默认 MockIdentityProvider
```

其他 Principal、Mock Provider、Middleware、Dependency 和验证任务保持不变。

- [ ] **Step 4: 严格校验门户身份 change 与全部现行 specs**

Run:

```powershell
openspec validate add-portal-identity-mock-chain --type change --strict --no-interactive
openspec validate --specs --strict --no-interactive
openspec status --change add-portal-identity-mock-chain
```

Expected:

```text
Change 'add-portal-identity-mock-chain' is valid
All artifacts complete!
```

现行 specs 校验不得再列出 `chat-demo`。

- [ ] **Step 5: 提交规格与提案收缩**

```powershell
git add -- openspec/specs/chat-demo/spec.md openspec/changes/add-portal-identity-mock-chain
git commit -m "docs: remove chat demo capability"
```

### Task 5: 全仓残留检查与完整回归

**Files:**
- Verify only: `backend/`
- Verify only: `Makefile`
- Verify only: `openspec/`

**Interfaces:**
- Consumes: Tasks 1-4 的清理结果。
- Produces: 可验证的 Document-only 当前基线。

- [ ] **Step 1: 搜索 Agent/Chat 运行时残留**

Run:

```powershell
rg -n --hidden --glob '!**/.git/**' --glob '!openspec/changes/archive/**' --glob '!docs/superpowers/specs/2026-06-29-chat-demo-design.md' "app\.domains\.agent|app\.services\.agent_api|app\.contracts\.agent|app\.entrypoints\.agent_api|dev-agent-api|AGENT_API_PORT" .
```

Expected: 无输出。历史归档和历史设计允许保留 Agent/Chat 文本。

- [ ] **Step 2: 确认 Document 使用的 OpenAI 能力仍存在**

Run:

```powershell
rg -n "openai_api_key|openai_base_url|openai_model|OpenAIEmbeddings|ChatOpenAI" backend/app/core/config.py backend/app/domains/document backend/app/entrypoints/document_worker.py backend/app/entrypoints/celery_worker.py backend/pyproject.toml
```

Expected: 能找到 Settings 中三个 OpenAI 字段、Document 的 `OpenAIEmbeddings` 以及 Worker/Celery 的 `ChatOpenAI` 使用点。

- [ ] **Step 3: 运行完整后端测试**

Run:

```powershell
Set-Location backend
uv run pytest -q
```

Expected: 全部测试 PASS，无 collection error、import error 或失败测试。

- [ ] **Step 4: 检查工作树与提交历史**

Run:

```powershell
git status --short
git log -5 --oneline
```

Expected: 没有遗漏的已跟踪修改；若只剩用户原有的未跟踪文件，明确列出且不删除。
