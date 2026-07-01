# Frontend

Next.js + Tailwind 文档上传测试页，用于端到端调用后端上传接口。

## 本地运行

```bash
npm install
npm run dev
```

默认页面地址：

```text
http://localhost:3000
```

页面会请求同源 `/api/v1/document/upload`，Next.js rewrite 默认转发到：

```text
http://localhost:8000/api/v1/document/upload
```

如果后端地址不同，可以启动前设置：

```bash
$env:API_BASE_URL="http://localhost:8000"
npm run dev
```
