## ADDED Requirements

### Requirement: 公共请求身份模型
系统 SHALL 提供统一的请求级 `Principal`，至少包含稳定用户标识 `user_id` 和当前租户标识 `tenant_id`，供不同 API 服务以相同方式消费身份。

#### Scenario: 身份模型包含用户和租户
- **WHEN** 身份提供器成功恢复一次请求的身份
- **THEN** 生成的 `Principal` 同时包含非空 `user_id` 和非空 `tenant_id`

### Requirement: 默认 Mock 身份
系统 SHALL 在不增加 Settings 配置且请求未携带 Mock 身份 Header 时，为受保护 HTTP 请求生成固定的默认开发身份。

#### Scenario: 未提供 Mock Header
- **WHEN** 受保护 HTTP 请求未携带 `X-Mock-User-Id` 和 `X-Mock-Tenant-Id`
- **THEN** 当前 Principal 的 `user_id` 为 `dev-user-001`，且 `tenant_id` 为 `dev-tenant-001`

### Requirement: Mock 身份 Header 覆盖
系统 SHALL 允许调用方通过 `X-Mock-User-Id` 和 `X-Mock-Tenant-Id` 分别覆盖默认用户和默认租户，以支持本地联调与隔离测试。

#### Scenario: 同时覆盖用户和租户
- **WHEN** 请求携带 `X-Mock-User-Id: user-002` 和 `X-Mock-Tenant-Id: tenant-002`
- **THEN** 当前 Principal 的 `user_id` 为 `user-002`，且 `tenant_id` 为 `tenant-002`

#### Scenario: 只覆盖用户
- **WHEN** 请求只携带 `X-Mock-User-Id: user-003`
- **THEN** 当前 Principal 的 `user_id` 为 `user-003`，且 `tenant_id` 保持默认值 `dev-tenant-001`

### Requirement: Middleware 在路由前恢复身份
系统 SHALL 通过纯 ASGI `IdentityMiddleware` 在受保护 HTTP 路由执行前调用 Mock 身份提供器，并将生成的 `Principal` 写入请求 state。

#### Scenario: 受保护请求进入路由
- **WHEN** 一个受保护 HTTP 请求通过 IdentityMiddleware
- **THEN** 下游路由执行前 `request.state.principal` 已包含该请求的 Principal

#### Scenario: 非 HTTP scope
- **WHEN** IdentityMiddleware 收到非 HTTP scope
- **THEN** Middleware 不生成 Principal，并将 scope 原样交给下游应用

### Requirement: 身份处理不干扰流式响应
IdentityMiddleware MUST NOT 读取请求体或包装下游响应流，并 SHALL 在请求入口只恢复一次 Principal。

#### Scenario: 流式接口使用请求身份
- **WHEN** 受保护的流式接口建立响应并持续输出数据
- **THEN** 流式处理使用请求入口生成的同一个 Principal，且 Middleware 不拦截持续输出

### Requirement: 公开健康检查绕过身份处理
系统 SHALL 允许每个 API 应用将 `/health` 声明为公开精确路径，公开路径请求不要求生成 Principal。

#### Scenario: 无身份访问健康检查
- **WHEN** 客户端请求 Agent API 或 Document API 的 `/health`
- **THEN** 请求不调用 Mock 身份提供器并正常进入健康检查路由

### Requirement: Dependency 统一暴露当前身份
系统 SHALL 提供 FastAPI Dependency，从请求 state 中返回当前 `Principal`；业务路由不得自行解析 Mock 身份 Header。

#### Scenario: Dependency 读取已恢复身份
- **WHEN** 受保护路由声明当前身份 Dependency 且 Middleware 已写入 Principal
- **THEN** Dependency 返回同一个 Principal 实例

#### Scenario: 请求上下文缺少身份
- **WHEN** 当前请求没有 `request.state.principal` 却调用身份 Dependency
- **THEN** 系统返回 HTTP 401

### Requirement: 两个 API 服务共享身份链路
Agent API 和 Document API SHALL 分别显式注册同一公共 IdentityMiddleware，并默认装配 Mock 身份提供器。

#### Scenario: Agent API 消费 Mock 身份
- **WHEN** 受保护请求进入 Agent API
- **THEN** Agent API 路由能够通过公共 Dependency 取得 Mock Principal

#### Scenario: Document API 消费 Mock 身份
- **WHEN** 受保护请求进入 Document API
- **THEN** Document API 路由能够通过公共 Dependency 取得 Mock Principal

### Requirement: 本阶段不依赖真实门户
系统 MUST NOT 在本阶段调用统一门户、IAM 或 `/who`，也 MUST NOT 要求真实 `user-info`、JWT 或新增身份 Settings 才能完成请求身份恢复。

#### Scenario: 本地独立运行身份链路
- **WHEN** 开发者在没有门户和 IAM 连接的本地环境启动任一 API 服务
- **THEN** 受保护请求仍可通过默认 Mock 身份完成 Principal 恢复
