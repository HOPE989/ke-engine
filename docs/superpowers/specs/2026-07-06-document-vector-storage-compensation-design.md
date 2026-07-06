# 文档向量存储补偿任务设计

## 背景

当前文档入库链路会把切分结果写入 `knowledge_segment`，把文档推进到 `CHUNKED`，然后发布 Kafka 事件触发 embedding 和向量存储。Kafka worker 消费 `document.embed_store.requested` 消息后，会调用 `run_document_vector_storage(doc_id)` 处理指定文档。

现有向量存储链路已经具备这些关键安全语义：

- Kafka offset 只在 `handle_document_vector_storage_message()` 中提交。
- `run_document_vector_storage(doc_id)` 不会提交 Kafka offset。
- `VECTOR_STORED` 文档和非 `CHUNKED` 文档会被幂等处理。
- Redis 文档级锁会阻止同一文档并发向量化。
- `store_document_vectors()` 会在重试前清理 Elasticsearch 残留向量，并在失败后清理本轮副作用。
- segment 回填和 document 完成状态更新在同一个数据库事务中提交或回滚。

本次增强是在正常 Kafka 链路之外，增加一个定时补偿路径，用来处理长期停留在 `CHUNKED` 的文档。

## 目标

- 增加一个针对 stale `CHUNKED` 文档的定时补偿任务。
- 使用 Celery 和现有 Redis 基础设施承载定时调度和任务执行。
- 补偿任务直接复用现有向量存储业务入口，不补投 Kafka 消息。
- Kafka offset commit 逻辑继续只保留在 Kafka worker 中。
- 保留现有 Redis 文档级锁和状态幂等语义。
- 首版只覆盖文档向量存储补偿，不扩展到其他后台任务体系。

## 非目标

- 不替换正常 Kafka 入库链路。
- 不引入 XXL-JOB 或 pyxxl。
- 不为正常文档入库新增第二套消息队列。
- 不从补偿任务直接调用底层 `store_document_vectors()`。
- 不在补偿任务首版中重构整个 document worker 模块。
- 不加入死信队列、重试次数持久化或管理后台页面。

## 设计

### 定时任务方案

使用 Celery + Redis：

- Redis 已经是后端现有基础设施。
- Celery Beat 负责周期性触发任务。
- Celery Worker 负责执行补偿任务。
- 不需要 XXL-JOB admin 回调本地 executor。
- 不把定时器嵌入 FastAPI Web 进程。

运行形态：

```text
Celery Beat
  -> 投递 document vector-storage compensation task
Redis broker
  -> 保存并分发任务
Celery Worker
  -> 执行补偿任务
  -> 调用 run_document_vector_storage(doc_id)
```

FastAPI 进程继续只负责 HTTP 请求。现有 Kafka worker 继续只负责 Kafka 消费和 Kafka offset commit。

### 业务入口复用

补偿任务直接复用：

```python
await run_document_vector_storage(doc_id)
```

在补偿任务中，返回值含义解释为：

- `True`：本轮处理完成，或文档已处于终态，或文档无需处理。
- `False`：本轮没有完成，后续定时任务可再次扫描重试。

补偿任务禁止调用：

```python
handle_document_vector_storage_message(...)
```

因为该函数拥有 Kafka commit 行为。

补偿任务也禁止调用：

```python
store_document_vectors(...)
```

因为该函数假设调用方已经完成 document 状态校验和运行时资源构造。

### 扫描规则

每轮补偿扫描 stale 文档：

```sql
status = 'CHUNKED'
and updated_at < now() - interval '<configured threshold>'
```

首版默认值：

- stale 阈值：5 分钟
- Celery Beat 间隔：5 分钟

这些值作为首版代码常量保留，不新增 settings。首版不增加 doc 级扫描 limit。补偿任务扫描到的是候选文档集合，然后逐个调用 `run_document_vector_storage(doc_id)`。单个文档内部的 segment 分页继续由现有业务方法负责。

### 冲突处理

Kafka worker 和 Celery 补偿任务可能同时处理同一个 `doc_id`。正确性依赖已有文档级锁和状态幂等：

```text
document:{doc_id}:embed-store
```

如果补偿任务先拿到锁：

```text
Celery compensation 处理 CHUNKED -> VECTOR_STORED
Kafka worker 看到 lock busy，不提交 Kafka offset
Kafka 消息后续重投
Kafka worker 看到 VECTOR_STORED，幂等提交 Kafka offset
```

如果 Kafka worker 先拿到锁：

```text
Kafka worker 处理 CHUNKED -> VECTOR_STORED
Celery compensation 看到 lock busy，或稍后看到非 CHUNKED 终态
Celery compensation 记录跳过或失败，然后退出当前 doc
```

补偿任务扫描得到的只是候选集，不代表这些文档在执行时仍然需要处理。每次真正执行时都以 `run_document_vector_storage(doc_id)` 内部读取到的实时 document 状态为准。如果某个文档已经被 Kafka worker 或前面的补偿调用推进到 `VECTOR_STORED`，后续调用会被幂等掉并返回成功。

首版不增加全局补偿任务锁。部署上保证只启动一个 Celery Beat；单文档正确性由已有文档级锁和状态幂等兜底。

### Celery 运行边界

新增 Celery app 模块：

```text
backend/app/infrastructure/celery_app.py
```

它负责：

- 创建 Celery app。
- 从 settings 读取 Redis broker 配置。
- 配置 JSON 序列化。
- 使用 UTC 时区，除非项目后续统一其他时区。
- 注册文档向量存储补偿任务的周期调度。

新增进程级 Celery worker 入口：

```text
backend/app/workers/celery_worker.py
```

它负责汇总所有模块的 Celery tasks，并作为 `celery -A` 的统一入口。该文件不写业务逻辑，只导入基础设施层 Celery app 并声明 task include 列表。这样它和现有 `backend/app/workers/kafka_worker.py` 的定位一致：`kafka_worker.py` 汇总模块 Kafka consumers，`celery_worker.py` 汇总模块 Celery tasks。

新增补偿任务模块：

```text
backend/app/modules/document/tasks/vector_storage_compensation.py
```

Celery task 可以是同步 wrapper，通过 `asyncio.run()` 调用异步补偿函数。异步补偿函数负责扫描所有 stale 文档并逐个调用 `run_document_vector_storage(doc_id)`。

扫描阶段使用独立的短数据库 session，并在逐个处理文档前关闭。这样避免和 `run_document_vector_storage()` 的运行时生命周期相互影响；当前 `run_document_vector_storage()` 会为每个 doc 初始化并关闭运行时资源。

本地 Windows 开发如果默认 worker 并发模型有问题，使用 `solo` 或 `threads` pool：

```bash
celery -A app.workers.celery_worker.celery_app worker -l INFO --pool=solo
celery -A app.workers.celery_worker.celery_app beat -l INFO
```

生产环境使用较低的固定并发。首版不在补偿任务内部增加 doc 级分页或 limit；如果后续观察到大量失败文档导致任务时间不可控，再单独引入文档级扫描上限。

## 组件

### Celery App

职责：

- 统一创建 Celery app。
- 注册 periodic schedule。
- 将 Celery 运行配置和 FastAPI lifespan、Kafka worker 启动逻辑隔离。

依赖：

- Redis broker。
- 后端 settings。
- 文档补偿任务模块。

### Celery Worker 入口

职责：

- 作为 `celery -A` 的进程级启动入口。
- 汇总所有模块的 Celery task 模块。
- 暴露 `celery_app` 给 Celery CLI。
- 不承载具体业务逻辑。

建议结构：

```python
from app.infrastructure.celery_app import create_celery_app

celery_app = create_celery_app(
    include=[
        "app.modules.document.tasks.vector_storage_compensation",
    ]
)
```

后续其他模块增加定时任务时，只需要把对应 task 模块加入 include 列表。

### 文档补偿任务

职责：

- 周期性运行。
- 扫描 stale `CHUNKED` 文档。
- 对每个候选文档调用 `run_document_vector_storage(doc_id)`。
- 记录成功、跳过、失败和总数。

依赖：

- `DocumentRepository` 的 stale 文档扫描方法。
- 现有向量存储入口。

### Repository 扫描方法

职责：

- 返回 stale `CHUNKED` 文档 ID。
- 按 `updated_at`、`doc_id` 稳定排序。

扫描 SQL 不应该散落在 Celery task 内，应放在 `DocumentRepository` 中。

### 现有向量存储入口

职责：

- 继续服务 Kafka worker。
- 同时作为补偿任务复用的高层文档处理入口。

首版不要求改变 `run_document_vector_storage()` 的行为。后续如果有更多调用方，再考虑抽出独立 service 入口。

## 数据流

```text
1. 正常链路完成文档切分。
2. 文档状态变为 CHUNKED。
3. Kafka 事件发布，正常情况下由 Kafka worker 处理。
4. 如果文档超过阈值仍停留在 CHUNKED，Celery Beat 触发补偿任务。
5. Celery Worker 扫描 stale CHUNKED 文档。
6. 对每个候选文档调用 run_document_vector_storage(doc_id)。
7. 现有 workflow 获取锁、清理 ES 残留、写向量、回填 segment、double-check，并推进文档到 VECTOR_STORED。
8. 如果候选文档在执行前已被其他路径推进到 VECTOR_STORED，run_document_vector_storage 内部实时状态检查会幂等返回成功。
9. 延迟或重复到达的 Kafka 消息后续通过状态幂等变成无害消息，并正常 commit。
```

## 错误处理

- 文档级锁被占用时，`run_document_vector_storage()` 返回 retryable failure，补偿任务记录失败并继续处理后续文档。
- OpenAI、Elasticsearch、Redis 或数据库异常继续由现有向量存储逻辑处理，文档保持可重试。
- 文档在补偿处理前已经变成 `VECTOR_STORED` 时，现有幂等逻辑返回成功。
- 单个文档失败不应导致整轮补偿任务失败。
- 任务级灾难性异常可以抛出，让 Celery 记录任务失败。

## 测试

需要覆盖：

- Repository scan 只返回 stale `CHUNKED` 文档，并验证排序。
- 补偿任务会对 stale 候选文档调用 `run_document_vector_storage()`。
- 补偿任务扫描到的候选文档如果在执行前已变为 `VECTOR_STORED`，由 `run_document_vector_storage()` 幂等返回成功。
- 补偿任务把 `True` 结果计为成功。
- 补偿任务把 `False` 结果计为失败或可重试，不因单文档失败抛出。
- 补偿任务不会调用 Kafka consumer commit 相关代码。
- Celery app 注册了固定周期的补偿任务。

现有 worker/workflow 测试继续覆盖文档级锁、终态幂等、ES 清理、DB 回滚和 Kafka commit 语义。

## 上线步骤

1. 增加 Celery 依赖和补偿任务代码常量。
2. 增加 repository stale 文档扫描方法。
3. 增加 Celery app 和文档补偿任务。
4. 增加 `backend/app/workers/celery_worker.py` 作为统一 Celery 入口。
5. 增加本地启动命令或 Makefile target。
6. 跑 focused tests。
7. 和 API、Kafka worker 一起启动 Celery worker 与 Celery beat。

## 已确认决策

- 使用 Celery + Redis 做定时补偿。
- 补偿任务直接调用 `run_document_vector_storage(doc_id)`。
- 不补投 Kafka 消息。
- 首版不加全局补偿任务锁。
- 首版不加 doc 级扫描分页或 limit；补偿任务扫描所有 stale `CHUNKED` 候选文档并逐个处理。
- 候选文档执行时以 `run_document_vector_storage(doc_id)` 内部实时状态和文档级锁为准。
- 增加 `backend/app/workers/celery_worker.py` 作为进程级 Celery task 汇总入口。
- 首版不抽独立 service 入口，等有更多调用方或语义变复杂时再整理。
