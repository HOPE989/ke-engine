## 1. 身份链路测试基线

- [x] 1.1 为 `Principal` 和 Mock 身份提供器增加失败测试，覆盖固定默认用户/租户、两个 Header 同时覆盖及单 Header 覆盖
- [x] 1.2 为纯 ASGI IdentityMiddleware 增加失败测试，覆盖路由前写入 state、`/health` 绕过、非 HTTP scope 原样传递以及不干扰流式响应
- [x] 1.3 为当前身份 Dependency 增加失败测试，覆盖返回同一 Principal 实例和缺失身份时返回 401

## 2. 公共身份包实现

- [x] 2.1 实现公共身份包，包含不可变 `Principal`、Provider 协议、`MockIdentityProvider` 和默认 Mock 身份值
- [x] 2.2 实现纯 ASGI `IdentityMiddleware`，按 Request → Middleware → Provider → Principal 顺序恢复身份并写入 scope state
- [x] 2.3 实现 FastAPI 当前身份 Dependency，确保业务代码无需读取 Mock Header

## 3. API 服务装配与清理

- [x] 3.1 增加服务装配失败测试，证明 Document API 注册公共身份链路且 `/health` 保持公开
- [x] 3.2 在 Document API 的 `create_app()` 中显式注册 IdentityMiddleware 和默认 MockIdentityProvider

## 4. 验证

- [x] 4.1 运行公共身份包及 Document API 的定向测试，确认默认身份、Header 覆盖、请求上下文和公开路径行为符合 spec
- [x] 4.2 运行完整后端测试套件，确认身份 Middleware 装配和残留清理未破坏现有功能
- [x] 4.3 运行 OpenSpec 校验并确认变更制品和实现任务保持一致
