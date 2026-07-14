## Why

当前两个 FastAPI API 服务尚未形成统一的请求身份恢复链路，业务代码无法通过稳定方式取得当前用户与租户。现阶段需要先用 Mock 身份走通统一门户鉴权结果进入应用后的消费链路，为后续替换为真实门户 Header 解析建立最小公共骨架。

## What Changes

- 新增公共请求身份模型 `Principal`，统一表示当前用户、租户及可选展示信息。
- 新增默认 Mock 身份提供器，支持固定默认身份，并允许通过 Mock Header 覆盖用户和租户。
- 新增纯 ASGI 身份 Middleware，在受保护 HTTP 请求进入路由前恢复身份并写入请求上下文。
- 新增 FastAPI Dependency，供业务路由从请求上下文读取当前 `Principal`。
- 在 Agent API 和 Document API 中注册同一套公共身份链路，同时允许健康检查绕过身份处理。
- 删除未被实际业务使用的身份、密码哈希占位实现及其对应测试。
- 增加覆盖默认身份、Header 覆盖、公开路径、服务装配和请求上下文传递的测试。
- 本阶段不增加 Settings 配置，不连接统一门户、IAM 或 `/who`，不解析真实 `user-info`，也不实现 JWT 验签和业务资源授权。

## Capabilities

### New Capabilities

- `portal-identity-consumption`: 使用默认 Mock 身份模拟统一门户鉴权结果，并通过公共 Middleware、请求级 Principal 和 Dependency 走通两个 FastAPI 服务的身份消费链路。

### Modified Capabilities

无。

## Impact

- 影响 `backend/app` 下的公共身份模块、Agent API 和 Document API 应用装配。
- 清理当前未使用的 `backend/app/contracts/identity` 占位契约与本地密码哈希残留。
- 不增加第三方依赖，不修改数据库结构，不增加对外身份接口，不修改现有业务资源授权规则。
- 后续真实门户接入可通过新增或替换 Identity Provider 完成，Middleware、Dependency 和业务侧读取方式保持不变。
