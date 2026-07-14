## Context

`ke-engine` 当前由 Agent API 和 Document API 两个独立 FastAPI 应用组成，二者尚未共享请求身份恢复机制。现阶段只需要模拟统一认证网关已经完成鉴权并把身份结果交给应用的场景，以验证“请求进入—恢复身份—写入上下文—业务读取”的完整链路；真实门户协议、Token 校验和运行模式切换均不在本次范围内。

现有身份契约与密码哈希代码没有实际业务依赖，可作为占位残留清理。实现应保持足够简单，并为后续用真实门户解析替换 Mock 身份来源保留清晰接缝。

## Goals / Non-Goals

**Goals:**

- 为两个 FastAPI API 应用提供相同的请求级 `Principal`。
- 默认使用固定 Mock 身份，并允许测试或本地调用通过两个 Mock Header 覆盖用户和租户。
- 在路由执行前由纯 ASGI Middleware 恢复身份，并通过 FastAPI Dependency 统一读取。
- 不干扰健康检查、请求体和流式响应。
- 用最少代码和测试证明公共身份消费链路已经贯通。

**Non-Goals:**

- 不连接统一门户、IAM、认证网关或 `/who`。
- 不解析 `user-info`、`gc-authentication` 等真实门户 Header，不验证 JWT。
- 不增加 Settings、环境模式或运行时 Provider 切换配置。
- 不实现用户表、角色系统、租户数据过滤或资源所有权授权。
- 不提供独立身份微服务或正式的当前用户查询 API。
- 不为 WebSocket、Worker、Kafka 或 Celery 构造请求身份。

## Decisions

### 1. 使用一个轻量公共身份模块

第一阶段将 `Principal`、Mock Provider、纯 ASGI Middleware 和 FastAPI Dependency 放在同一公共身份模块中，避免提前拆分多层目录和抽象。两个 API 应用直接导入并注册该模块。

备选方案是立即建立包含 `providers/`、`errors.py`、`config.py` 等文件的完整身份包；当前只有一个 Mock 实现，拆分收益不足，待真实门户 Provider 加入时再按复杂度重构。

### 2. Middleware 控制流程，Provider 只负责生成身份

请求执行顺序固定为：

```text
HTTP Request
    -> IdentityMiddleware
    -> MockIdentityProvider.authenticate()
    -> Principal
    -> request.state.principal
    -> CurrentPrincipal Dependency
    -> Route
```

Middleware 负责公开路径判断和请求上下文写入；Mock Provider 只根据 Header 与默认值生成 `Principal`。Provider 通过构造参数交给 Middleware，不引入抽象基类或依赖注入容器。

### 3. Mock 身份零配置可用

未提供 Mock Header 时使用固定值：

- `user_id = dev-user-001`
- `tenant_id = dev-tenant-001`

调用方可分别用 `X-Mock-User-Id` 和 `X-Mock-Tenant-Id` 覆盖默认值。第一阶段只保留走通用户与当前租户链路所需字段，不引入未被业务使用的角色和租户集合模型。

备选方案是要求每个请求必须携带完整 Mock Header；固定默认值更适合当前的本地联调目标，并减少前端和现有接口测试的接入成本。

### 4. 使用纯 ASGI Middleware

Middleware 只处理 `http` scope，不读取请求体、不包装响应流，并在调用下游应用前写入 `scope["state"]["principal"]`。这样可以兼容现有流式聊天接口，并保证一次请求只解析一次身份。

非 HTTP scope 原样传递。公开路径第一阶段仅使用应用装配时传入的精确路径集合，不建设通配符或前缀匹配系统。

### 5. 业务代码只能通过 Dependency 读取身份

公共 Dependency 从 `request.state.principal` 返回 `Principal`。缺少身份时返回 401，避免业务路由直接读取 Mock Header，也让未来切换真实门户 Provider 时不修改业务调用方式。

### 6. 两个 API 应用显式注册

Agent API 和 Document API 分别在自己的 `create_app()` 中注册同一个 Middleware，并将 `/health` 作为公开路径。Worker 进程没有 HTTP 请求链路，不注册该 Middleware。

## Risks / Trade-offs

- [固定 Mock 身份不具备真实安全性] → 明确限定为链路演练，不把本阶段实现视为正式门户鉴权能力。
- [没有 Settings 意味着无法运行时切换 Provider] → 当前刻意选择代码装配；正式门户接入时再引入真实 Provider 和必要配置。
- [单模块未来可能变大] → 当前优先最小实现，只有真实门户解析、`/who` 或多种 Provider 出现后才拆包。
- [默认身份会让受保护接口在无 Header 时通过] → 这是本阶段本地联调的预期行为，由测试明确固化，正式接入时必须替换。
- [删除残留代码可能暴露隐含依赖] → 删除后运行完整后端测试，若存在真实调用则在实现阶段按实际用途重新评估。

## Migration Plan

1. 删除未使用的身份契约、密码哈希实现及对应测试。
2. 加入公共身份模块及其单元测试。
3. 在 Agent API 和 Document API 中注册 Middleware。
4. 增加服务级测试，确认健康检查绕过且受保护请求可以读取 Principal。
5. 运行完整后端测试；回滚时移除两处 Middleware 注册并恢复被删除文件即可。

## Open Questions

无。本阶段使用固定 Mock 身份和两个覆盖 Header，真实门户字段与安全边界留到后续变更讨论。
