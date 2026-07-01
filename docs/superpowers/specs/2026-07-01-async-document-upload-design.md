# 异步文档上传设计

## 目标

将文档上传链路从“HTTP 请求内同步解析到可用结果”改为“HTTP 请求只完成接收与原文持久化，后续解析、切分、入库由后台任务推进”。

这次改造同时把 `doc_id` 从数据库自增 ID 改为应用侧 Snowflake 分布式 ID，但字段名仍保持 `doc_id`。

## 范围

本次设计包含：

- `knowledge_document.doc_id` 改为 Snowflake 生成的 `BIGINT`，字段名不变。
- `POST /api/v1/document/upload` 统一异步化，成功接收后返回 `202 Accepted`。
- 上传请求只推进到 `UPLOADED`，不在请求内调用 MinerU、轮询、解 ZIP、上传转换产物。
- 使用 Celery + Redis 执行解析、切分、向量化/入库等后台阶段。
- 使用定时任务基于 `knowledge_document.status + updated_at` 做补偿，不新增 job 表。
- 使用 `python-redis-lock` 提供带自动续期的 Redis 分布式锁，满足长时间解析任务的锁续期需求。
- 继续使用数据库 expected-state update 保护状态机推进。

不包含：

- 认证、授权。
- 文档 chunk、embedding、向量库写入的具体实现细节。
- 独立 job/outbox 表。
- 把 Python worker 改为 Java worker 或引入 Redisson sidecar。

## 业务状态机

`knowledge_document.status` 只表达业务处理阶段，不表达队列技术状态。

状态机为：

```text
INIT
  -> UPLOADED
  -> CONVERTING
  -> CONVERTED
  -> CHUNKED
  -> VECTOR_STORED / STORED
```

状态含义：

- `INIT`：文档元数据已创建，原始文件尚未确认上传完成。
- `UPLOADED`：原始文件已上传到 MinIO，可以进入后台解析。
- `CONVERTING`：解析任务已抢占该文档，正在执行 MinerU 或其他格式转换。
- `CONVERTED`：已产出标准 Markdown/文本，`converted_doc_url` 可用。
- `CHUNKED`：已完成文档切分。
- `VECTOR_STORED`：已完成向量化并写入向量存储。
- `STORED`：已完成非向量化或最终存储流程。

不新增 `QUEUED`、`PROCESSING`、`FAILED` 这类队列态到 `knowledge_document.status`。

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
SNOWFLAKE_EPOCH_MS=1767225600000
```

推荐位分配：

```text
1 bit   符号位，固定 0
41 bit  项目 epoch 后的毫秒时间戳
10 bit  worker id，范围 0..1023
12 bit  同毫秒序列号，范围 0..4095
```

所有会生成 `doc_id` 的进程必须配置唯一 `SNOWFLAKE_WORKER_ID`。首版只要求 FastAPI API 进程生成文档 ID，后台 worker 只消费已有 `doc_id`。

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
  -> 标记 status=UPLOADED，写入 doc_url
  -> 尝试投递 convert task(doc_id)
  -> 返回 202，data.status=UPLOADED
```

响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "doc_id": 739482091234567168,
    "doc_title": "guide.pdf",
    "upload_user": "alice",
    "accessible_by": "team-a",
    "doc_url": "http://localhost:9000/documents/documents/739482091234567168/original/guide.pdf",
    "converted_doc_url": null,
    "status": "UPLOADED"
  }
}
```

如果 Celery 投递失败，只要原文已上传并且状态已落为 `UPLOADED`，上传接口仍可返回 `202`。后续由定时补偿扫描 `UPLOADED` 文档重新投递解析任务。

## 后台任务

后台任务只负责推进业务状态机，不创造独立业务事实。

转换任务：

```text
convert_document(doc_id)
  -> 获取 lock:document:{doc_id}:convert
  -> UPDATE status='CONVERTING'
     WHERE doc_id=:doc_id AND status='UPLOADED'
  -> 影响行数为 0：退出
  -> 读取 MinIO 原文
  -> 调用 MinerU 或其他解析器
  -> 上传 converted Markdown/assets
  -> UPDATE status='CONVERTED', converted_doc_url=:url
     WHERE doc_id=:doc_id AND status='CONVERTING'
  -> 释放锁
```

切分任务：

```text
chunk_document(doc_id)
  -> 获取 lock:document:{doc_id}:chunk
  -> UPDATE status='CHUNKED'
     WHERE doc_id=:doc_id AND status='CONVERTED'
  -> 执行切分并持久化切分结果
  -> 释放锁
```

存储/向量化任务：

```text
store_document(doc_id)
  -> 获取 lock:document:{doc_id}:store
  -> 从 CHUNKED 抢占
  -> 执行向量化/入库
  -> UPDATE status='VECTOR_STORED' 或 status='STORED'
  -> 释放锁
```

首版可以只实现 upload 到 convert 的异步解耦，但状态机和补偿策略必须给后续 `CHUNKED`、`VECTOR_STORED`、`STORED` 留出一致路径。

## 定时补偿

不新增 job 表。补偿任务以 `knowledge_document` 为唯一业务事实来源。

定时任务扫描：

```text
status='UPLOADED'   and updated_at < now - upload_grace_seconds
status='CONVERTING' and updated_at < now - converting_stale_seconds
status='CONVERTED'  and updated_at < now - converted_grace_seconds
status='CHUNKED'    and updated_at < now - chunked_grace_seconds
```

补偿行为：

- `UPLOADED` 超时：补投 `convert_document(doc_id)`。
- `CONVERTING` 超时：补投 `convert_document(doc_id)`，任务内通过锁和 expected-state 判断是否可恢复。
- `CONVERTED` 超时：补投 `chunk_document(doc_id)`。
- `CHUNKED` 超时：补投 `store_document(doc_id)`。

补偿任务不直接绕过 worker 业务函数。它只负责发现卡住状态并补投对应 Celery task。

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
    name=f"lock:document:{doc_id}:convert",
    expire=60,
    auto_renewal=True,
)
```

锁粒度：

```text
lock:document:{doc_id}:convert
lock:document:{doc_id}:chunk
lock:document:{doc_id}:store
```

锁只防止同一 `doc_id` 同一阶段被异步任务和定时补偿任务并发执行。最终正确性仍由数据库 expected-state update 保证。

## 并发控制

每个阶段都同时使用 Redis lock 和数据库 expected-state update。

示例：

```sql
UPDATE knowledge_document
SET status = 'CONVERTING'
WHERE doc_id = :doc_id
  AND status = 'UPLOADED'
```

处理规则：

- 抢不到 Redis 锁：说明同阶段任务正在运行，当前任务退出。
- 抢到锁但 expected-state update 影响行数为 0：说明状态已被其他任务推进或不满足前置条件，当前任务退出。
- Redis 锁过期或故障边界下出现重复执行：数据库 expected-state update 仍然阻止错误状态推进。

## 失败与重试

上传请求内失败：

- 原文上传失败：返回 `502 document storage failed`，文档保持 `INIT`。
- 初始持久化失败：返回 `500 document persistence failed`。
- 文件类型不支持或检测失败：维持现有错误契约。

后台解析失败：

- 可重试失败可以将状态从 `CONVERTING` 回退到 `UPLOADED`，由定时补偿再次投递。
- worker 崩溃可能让状态停留在 `CONVERTING`，定时补偿会扫描超时记录并补投转换任务。
- 首版不新增 `FAILED` 业务状态；失败详情如果需要，可后续增加独立错误字段，不改变主状态机。

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
UPLOADED / CONVERTING / CONVERTED / CHUNKED / VECTOR_STORED / STORED
```

## 实现边界

建议模块边界：

```text
backend/app/infrastructure/snowflake.py
  SnowflakeIdGenerator

backend/app/infrastructure/celery.py
  Celery app construction

backend/app/infrastructure/redis_lock.py
  python-redis-lock 封装，提供 document stage lock

backend/app/modules/document/workflow.py
  request-bound upload acceptance workflow

backend/app/modules/document/tasks.py
  Celery task wrappers and scheduled compensation tasks

backend/app/modules/document/processing.py
  convert/chunk/store worker-side workflows

backend/app/modules/document/repository.py
  expected-state lifecycle updates and stale-status scans
```

`app.infrastructure.mineru` 保持 MinerU provider 封装。官方 MinerU 的 `_poll_full_zip_url` 继续存在，但只在 worker 内执行，不再阻塞 HTTP 请求。

## 迁移影响

因为当前功能未上线，可以直接调整初始 migration：

- `knowledge_document.doc_id` 从 `BIGINT IDENTITY` 改为普通 `BIGINT PRIMARY KEY`。
- 状态约束扩展为：

```text
INIT, UPLOADED, CONVERTING, CONVERTED, CHUNKED, VECTOR_STORED, STORED
```

- 可增加 `file_type` 字段，避免 worker 重新运行 Magika。
- 不创建 `document_processing_job` 表。

## 测试策略

需要覆盖：

- Snowflake ID 生成、worker_id 校验、时钟回拨处理。
- `POST /document/upload` 成功返回 `202` 和 `UPLOADED`。
- 上传请求不调用 MinerU。
- 原文上传成功后即使 Celery 投递失败，也能通过定时补偿恢复。
- `convert_document` 使用 `python-redis-lock` 的 `auto_renewal=True`。
- 同一 `doc_id` 同一阶段抢不到锁时任务退出。
- expected-state update 防止重复状态推进。
- 定时补偿扫描 `UPLOADED`、`CONVERTING`、`CONVERTED`、`CHUNKED` 并补投对应任务。
- PDF worker 成功推进 `UPLOADED -> CONVERTING -> CONVERTED`。
- 后续 chunk/store worker 按状态机推进到 `CHUNKED`、`VECTOR_STORED` 或 `STORED`。
