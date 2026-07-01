# 异步文档上传设计

## 目标

将文档上传链路从“HTTP 请求内同步解析到可用结果”改为“HTTP 请求只完成接收与原文持久化，后续解析由后台任务自动推进到 `CONVERTED`”。

这次改造同时把 `doc_id` 从数据库自增 ID 改为应用侧 Snowflake 分布式 ID，但字段名仍保持 `doc_id`。

本设计对齐 `know-engine` 的产品语义：上传后的自动解析完成态是 `CONVERTED`；切分是后续独立大需求，不在本 spec 中实现。

## 范围

本次设计包含：

- `knowledge_document.doc_id` 改为 Snowflake 生成的 `BIGINT`，字段名不变。
- `POST /api/v1/document/upload` 异步化，成功接收原文后返回 `202 Accepted`。
- 上传请求只推进到 `UPLOADED`，不在请求内调用 MinerU、轮询、解 ZIP、上传转换产物。
- 使用 Celery + Redis 执行后台解析任务，将文档自动推进到 `CONVERTED`。
- 使用 `python-redis-lock` 提供带自动续期的 Redis 分布式锁，保护同一 `doc_id` 的解析任务不并发执行。
- 继续使用数据库 expected-state update 保护状态机推进。
- 提供状态查询接口，让客户端查看 `UPLOADED`、`CONVERTING`、`CONVERTED`。

不包含：

- 认证、授权。
- 文档切分、chunk 持久化、embedding、向量库写入。
- `CHUNKED`、`VECTOR_STORED`、`STORED` 等切分/入库状态。
- 独立 job/outbox 表。
- 定时补偿任务。
- `FAILED` 状态、失败详情字段、自动重试或手动 retry 接口。
- 上传请求分布式锁。
- 多版本。
- 把 Python worker 改为 Java worker 或引入 Redisson sidecar。

## 业务状态机

`knowledge_document.status` 只表达文档上传与解析阶段，不表达队列技术状态。

本 spec 的状态机为：

```text
INIT
  -> UPLOADED
  -> CONVERTING
  -> CONVERTED
```

状态含义：

- `INIT`：文档元数据已创建，原始文件尚未确认上传完成。
- `UPLOADED`：原始文件已上传到 MinIO，解析任务尚未完成。该状态也可能表示 Celery 投递失败或解析失败后的残留状态，首版不自动处理。
- `CONVERTING`：后台解析任务已抢占该文档，正在执行 MinerU 或其他格式转换。
- `CONVERTED`：已产出标准 Markdown/文本，`converted_doc_url` 可用。后续切分需求以该状态作为前置条件，但不在本 spec 中实现。

不新增 `QUEUED`、`PROCESSING`、`FAILED` 这类队列态或失败态到 `knowledge_document.status`。

## `doc_id` 生成

`doc_id` 仍然是系统对外公开的文档 ID，但不再由数据库 identity/sequence 生成。

上传边界在创建 `INIT` 行前生成 ID：

```text
doc_id = snowflake.next_id()
INSERT knowledge_document(doc_id, status='INIT', ...)
```

该 `doc_id` 用于：

- API 响应。
- MinIO 对象路径：`documents/{doc_id}/...`。
- Celery task 参数。
- 状态查询接口路径。
- 分布式锁 key。

Snowflake 配置：

```text
SNOWFLAKE_WORKER_ID=1
```

推荐位分配：

```text
1 bit   符号位，固定 0
41 bit  项目 epoch 后的毫秒时间戳
10 bit  worker id，范围 0..1023
12 bit  同毫秒序列号，范围 0..4095
```

所有会生成 `doc_id` 的进程必须配置唯一 `SNOWFLAKE_WORKER_ID`。首版只要求 FastAPI API 进程生成文档 ID，后台 worker 只消费已有 `doc_id`。

API JSON 响应中的 `doc_id` 建议序列化为字符串，避免 JavaScript `Number` 精度丢失；数据库和 Python 内部仍按整数处理。

## 上传流程

`POST /api/v1/document/upload` 成功时返回 `202 Accepted`，响应体继续使用 `APIResponse[DocumentMetadata]`。

请求内流程：

```text
POST /document/upload
  -> 校验 multipart 字段、文件名、大小和内容
  -> 检测文件类型
  -> 生成 Snowflake doc_id
  -> 创建 knowledge_document(status=INIT)
  -> 上传原始文件到 MinIO
  -> 标记 status=UPLOADED，写入 doc_url 和 file_type
  -> 尝试投递 convert_document(doc_id)
  -> 返回 202，data.status=UPLOADED
```

上传请求不拿 Redis 分布式锁。每次上传都会生成新的 `doc_id`，对象路径也是 `documents/{doc_id}/...`，不存在多个上传请求争抢同一文档状态的问题。上传阶段的正确性依赖 Snowflake ID 唯一性、数据库主键约束和 `INIT -> UPLOADED` expected-state update。

响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "doc_id": "739482091234567168",
    "doc_title": "guide.pdf",
    "upload_user": "alice",
    "accessible_by": "team-a",
    "doc_url": "http://localhost:9000/documents/documents/739482091234567168/original/guide.pdf",
    "converted_doc_url": null,
    "status": "UPLOADED"
  }
}
```

如果 Celery 投递失败，只要原文已上传并且状态已落为 `UPLOADED`，上传接口仍返回 `202`。首版不做补偿、不做自动重试、不提供 retry 接口；该文档会保持 `UPLOADED`，由状态查询如实展示。

## 后台解析任务

后台解析任务只负责推进上传后的自动解析状态，不创造独立业务事实。

转换任务：

```text
convert_document(doc_id)
  -> 获取 lock:document:{doc_id}:convert
  -> UPDATE status='CONVERTING'
     WHERE doc_id=:doc_id AND status='UPLOADED'
  -> 影响行数为 0：退出
  -> 读取 MinIO 原文
  -> 根据 file_type 处理：
       PDF: 调用 MinerU，解 ZIP，上传 Markdown/assets
       Markdown/TXT: 直接发布为 converted 文档
  -> UPDATE status='CONVERTED', converted_doc_url=:url
     WHERE doc_id=:doc_id AND status='CONVERTING'
  -> 释放锁
```

首版不实现 `chunk_document`、`store_document` 或任何向量化任务。

## 分布式锁

解析是长任务，锁必须具备 Redisson watchdog 等价语义：

- 任务持有锁期间自动续期。
- worker 存活且续期线程正常时，锁不会因固定 TTL 过期。
- worker 崩溃后，锁能在 TTL 内自动释放。
- 释放锁必须校验持锁 token，不能误删其他 worker 的锁。

Python 实现选择：

```text
python-redis-lock
```

使用方式要求：

```python
redis_lock.Lock(
    redis_client,
    name=f"document:{doc_id}:convert",
    expire=60,
    auto_renewal=True,
)
```

锁粒度：

```text
lock:document:{doc_id}:convert
```

`python-redis-lock` 会给传入的 `name` 增加 `lock:` 前缀，因此代码传入 `document:{doc_id}:convert`，实际 Redis key 为 `lock:document:{doc_id}:convert`。

锁只防止同一 `doc_id` 的解析任务被重复投递、Celery 重试或多 worker 并发消费时同时执行。最终正确性仍由数据库 expected-state update 保证。

## 并发控制

后台解析阶段同时使用 Redis lock 和数据库 expected-state update。

抢占解析：

```sql
UPDATE knowledge_document
SET status = 'CONVERTING'
WHERE doc_id = :doc_id
  AND status = 'UPLOADED'
```

完成解析：

```sql
UPDATE knowledge_document
SET status = 'CONVERTED',
    converted_doc_url = :converted_doc_url
WHERE doc_id = :doc_id
  AND status = 'CONVERTING'
```

处理规则：

- 抢不到 Redis 锁：说明同一文档解析任务正在运行，当前任务退出。
- 抢到锁但 expected-state update 影响行数为 0：说明状态已被其他任务推进或不满足前置条件，当前任务退出。
- Redis 锁过期或故障边界下出现重复执行：数据库 expected-state update 仍然阻止错误状态推进。

## 失败语义

上传请求内失败：

- 文件类型不支持或检测失败：维持现有错误契约，并且不创建文档行。
- 初始持久化失败：返回通用 `500`。
- 原文上传失败：返回 `502 document storage failed`，文档保持 `INIT`。

上传请求内非失败：

- Celery 投递失败：上传接口仍返回 `202`，文档保持 `UPLOADED`。首版不补偿。

后台解析失败：

- 解析逻辑抛出可捕获异常：尝试将状态从 `CONVERTING` 回退到 `UPLOADED`。
- worker 崩溃、进程被 kill 或机器重启：文档可能停留在 `CONVERTING`。首版不补偿。
- 首版不新增 `FAILED` 业务状态，不记录 retry count，不记录 last error，不提供 retry 接口。

因此首版可能长期存在 `UPLOADED` 或 `CONVERTING` 文档。状态查询接口只负责如实展示，不负责恢复。

## API 契约

上传接口：

```text
POST /api/v1/document/upload
```

成功返回：

```text
HTTP 202 Accepted
data.status = "UPLOADED"
```

状态查询接口：

```text
GET /api/v1/document/{doc_id}
```

返回 `DocumentMetadata`，客户端通过 `status` 判断当前阶段：

```text
UPLOADED / CONVERTING / CONVERTED
```

状态展示建议：

```text
UPLOADED    原文已保存，解析未完成或解析失败残留
CONVERTING  正在解析
CONVERTED   解析完成，可供后续切分大需求使用
```

## 实现边界

建议模块边界：

```text
backend/app/infrastructure/snowflake.py
  SnowflakeIdGenerator

backend/app/infrastructure/celery.py
  Celery app construction

backend/app/infrastructure/redis_lock.py
  python-redis-lock 封装，提供 document convert lock

backend/app/modules/document/workflow.py
  request-bound upload acceptance workflow

backend/app/modules/document/tasks.py
  Celery task wrappers

backend/app/modules/document/processing.py
  convert worker-side workflow

backend/app/modules/document/repository.py
  expected-state lifecycle updates and document lookup
```

`app.infrastructure.mineru` 保持 MinerU provider 封装。官方 MinerU 的 `_poll_full_zip_url` 继续存在，但只在 worker 内执行，不再阻塞 HTTP 请求。

`DocumentObjectStorage` 需要支持 worker 从 MinIO 读取原文；现有上传能力之外，需要增加按 object key 下载 bytes 或 stream 的能力。

## 迁移影响

因为当前功能未上线，可以直接调整初始 migration：

- `knowledge_document.doc_id` 从 `BIGINT IDENTITY` 改为普通 `BIGINT PRIMARY KEY`。
- 状态约束限定为：

```text
INIT, UPLOADED, CONVERTING, CONVERTED
```

- 增加 `file_type` 字段，避免 worker 重新运行 Magika。
- 不创建 `document_processing_job` 表。
- 不为切分、向量化增加表结构或状态。

## 测试策略

需要覆盖：

- Snowflake ID 生成、worker_id 校验、时钟回拨处理。
- `knowledge_document.doc_id` 不再使用数据库 identity。
- `POST /document/upload` 成功返回 `202` 和 `UPLOADED`。
- API JSON 中 `doc_id` 以字符串返回。
- 上传请求不调用 MinerU。
- 上传请求不获取 Redis 分布式锁。
- 原文上传成功后即使 Celery 投递失败，接口仍返回 `202`，文档保持 `UPLOADED`。
- `convert_document` 使用 `python-redis-lock` 的 `auto_renewal=True`。
- 同一 `doc_id` 抢不到 convert 锁时任务退出。
- expected-state update 防止重复状态推进。
- PDF worker 成功推进 `UPLOADED -> CONVERTING -> CONVERTED`。
- Markdown/TXT worker 成功推进 `UPLOADED -> CONVERTING -> CONVERTED`。
- 解析失败时尝试 `CONVERTING -> UPLOADED`。
- `GET /document/{doc_id}` 返回 `UPLOADED`、`CONVERTING`、`CONVERTED` 状态。
