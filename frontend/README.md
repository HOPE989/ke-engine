# Frontend

Next.js + Tailwind 测试页，用于手动端到端调用后端文档和 Chat 接口。

## 本地运行

```bash
npm install
npm run dev
```

默认页面地址：

```text
http://localhost:3000
```

Chat 测试页：

```text
http://localhost:3000/chat
```

页面会请求同源 `/api/v1/document/*`，Next.js rewrite 默认转发到后端：

```text
http://localhost:8000/api/v1/document/*
```

Chat 页面请求同源 `/api/v1/chat/*`，默认转发到 Chat API：

```text
http://localhost:8001/api/v1/chat/*
```

页面会把上传接口返回的 `doc_id` 自动带到后续查询、切分和向量入库步骤；需要从中间步骤测试时也可以手动修改。

如果后端地址不同，可以启动前设置：

```bash
$env:API_BASE_URL="http://localhost:8000"
$env:CHAT_API_BASE_URL="http://localhost:8001"
npm run dev
```
