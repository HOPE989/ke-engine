# RAG入库链路 - 资源初始化生命周期治理

本文是中间讨论文档，用于记录当前关于 API、Kafka worker、Celery worker 资源初始化问题的讨论结论。后续正式进入 OpenSpec change 时，应以本文为背景材料继续细化 proposal、design、spec delta 和 tasks。

## 背景

当前项目里有不少资源是在请求、消息或任务执行路径上初始化的。这个模式会把初始化成本算到用户文档处理链路上：

- API 层可能在请求期重复构造配置。
- Kafka worker 在每条消息或每个文档处理时初始化 DB、Redis、模型、Elasticsearch 等资源。
- Celery 补偿任务通过 `asyncio.run()` 执行异步逻辑，并复用当前按文档初始化资源的向量存储入口。

这次需求的核心不是单点性能优化，而是统一资源生命周期：

```text
进程启动期创建长期资源
请求/消息/任务处理期只创建轻量上下文
进程关闭期统一释放长期资源
```

## 已确认约束

1. 配置文件不做热更新。
   修改 DB、Redis、Kafka、MinIO、OpenAI、Elasticsearch、embedding 维度等配置后，需要重启对应服务进程。

2. `/chat` 模块不纳入本次范围。
   该模块目前只是占位，后续会重做。

3. Celery 补偿任务不能补投 Kafka。
   之前设计已经否决过补投 Kafka，原因是会引入重复投递、offset 语义和补偿链路复杂度。补偿任务仍应直接处理 stale `CHUNKED` 文档。

4. Kafka offset commit 语义不改变。
   Kafka commit 仍只属于 Kafka consumer message handler，补偿任务不得调用带 commit 语义的函数。

5. 目标不是“所有对象都做单例”。
   目标是区分哪些资源应共享，哪些上下文必须每次创建。

## 当前问题梳理

### API 层

API 的文档模块已经有启动期 runtime：

- `document_runtime()` 在 FastAPI lifespan 中初始化 DB engine/session factory。
- 初始化 MinIO client、Redis client、Kafka producer、Magika、Snowflake ID generator。
- 文档请求通过 `DocumentRuntime` 复用这些资源。

当前主要问题：

- `get_config()` 每次请求调用 `get_request_settings()`，会重新构造完整 `Settings`。
- 这个设计像是在支持配置热更新，但大部分配置本质上是 startup-only。
- 即使请求期读到了新配置，已经初始化的 DB/Redis/Kafka/MinIO/模型资源也不会自动切换，容易形成“配置值是新的，资源还是旧的”的不一致。

倾向方案：

- FastAPI lifespan 启动期保存 settings snapshot。
- 请求期直接从 `app.state` 或 runtime 取配置。
- 若以后需要动态业务参数，应单独设计，不应重建完整基础设施配置。

### Kafka worker

Kafka worker 是当前资源初始化问题最严重的地方。

现状：

- `kafka_worker.py` 在同一个进程和同一个 asyncio event loop 中启动两个 consumer：
  - 文档转换 consumer。
  - 文档向量存储 consumer。
- 两个 consumer 共享 Python 进程内存和模块级全局变量。
- 但当前每条消息各自初始化和关闭资源。

转换 worker 问题：

- 每条消息创建 Redis client。
- 拿到锁后，每条消息 `init_engine()` / `close_engine()`。
- MinIO storage、MinerU client、图片总结 `ChatOpenAI` 都是任务内懒加载。
- 图片总结模型实际在 PDF 文档第一次处理图片时创建。

向量存储 worker 问题：

- 每个 doc 都 `init_engine()` / `close_engine()`。
- 每个 doc 创建 Redis client。
- 每个 doc 创建 `OpenAIEmbeddings`。
- 每个 doc 创建 `ElasticsearchStore`。
- 这会把 embedding 模型和 ES store 初始化成本放到文档处理路径上。

更严重的并发风险：

- `app.db.session` 使用模块级 `_engine` / `_session_factory`。
- Kafka worker 的两个 consumer 在同一进程内共享这组全局变量。
- 如果两个 consumer 并发处理消息，一边 `close_engine()` 可能清掉另一边正在使用或即将使用的全局 engine/session factory。

倾向方案：

```text
kafka_worker main
  -> 启动期创建 KafkaWorkerRuntime
     -> settings snapshot
     -> DB engine/session factory
     -> Redis client
     -> MinIO storage
     -> MinerU client
     -> image summary model
     -> embedding model
     -> Elasticsearch store/client
  -> conversion consumer 和 vector-storage consumer 共享 runtime
  -> 消息处理期只创建 per-doc lock、DB session/transaction、payload
```

### Celery worker

Celery 当前只作为定时补偿任务入口。

现状：

```python
@shared_task(...)
def compensate_stale_chunked_document_vectors_task():
    return asyncio.run(compensate_stale_chunked_document_vectors())
```

含义：

- Celery task 本身是同步函数。
- 每次任务执行时，`asyncio.run()` 临时创建一个 event loop。
- 异步补偿逻辑跑完后，该 event loop 被关闭。
- 任务之间没有天然共享的长期 async runtime。

当前补偿任务还会：

- 扫描 stale `CHUNKED` 文档时短生命周期初始化 DB。
- 对每个 doc 调用 `run_document_vector_storage(doc_id)`。
- 因此继承向量存储 worker 的 per-doc 初始化问题：每个 doc 重建 DB、Redis、embedding model、ES store。

讨论过但否决的方案：

- Celery 只扫描 stale doc 然后补投 Kafka 事件。
- 该方案不采用，因为之前明确否决过补投 Kafka。

可选方案：

1. 彻底方案：Celery worker 进程级 async runtime。

```text
Celery worker process
  -> Celery signal: worker_process_init
     -> 启动长期 asyncio loop
     -> 初始化补偿所需 runtime
  -> task 执行
     -> 同步 task 函数把 coroutine 提交到长期 loop
  -> Celery signal: worker_process_shutdown
     -> 关闭 runtime
     -> 停止 loop
```

优点：

- 符合“worker 启动期初始化长期资源”的目标。
- 可以避免每个 task 或每个 doc 重建重资源。
- 能保持“不补投 Kafka”的既有决策。

代价：

- Celery 主循环由 Celery 框架接管，不像 Kafka worker 有自己的 `asyncio.run(main())`。
- 需要用 Celery signal 接入启动/关闭生命周期。
- 如果使用 prefork，每个子进程都要各自初始化 runtime，不能在父进程初始化后 fork 继承连接。

2. 简化方案：每轮补偿任务初始化一次 runtime。

```text
compensation task starts
  -> init DB/Redis/embedding/ES once
  -> scan stale docs
  -> process doc 1
  -> process doc 2
  -> process doc 3
  -> close runtime
```

优点：

- 实现简单。
- 解决最重的“每个 doc 重建 embedding/ES store”问题。

缺点：

- 不是 worker 进程启动期初始化。
- 每轮补偿任务仍会初始化一次重资源。

当前倾向：

- OpenSpec 设计可以以彻底方案为目标。
- 如果实现风险较大，可在 tasks 中拆阶段，先做到每轮补偿一次 runtime，再推进到 Celery 进程级 async runtime。

## 资源共享边界

我们用 Java/Druid 类比来统一理解：

```text
DruidDataSource / 连接池
  -> 应用启动时创建，一个进程共享

Connection / SqlSession
  -> 每次数据库操作或事务从池里借
  -> 用完归还
  -> 不跨请求、消息、线程长期持有
```

映射到当前 Python 项目：

```text
SQLAlchemy AsyncEngine
  -> 类似连接池，进程级共享

async_sessionmaker
  -> session 工厂，进程级共享

AsyncSession
  -> 一次业务操作或事务上下文，每次创建，用完关闭
```

### 应共享的资源

这些资源昂贵、配置驱动、内部持有连接池或网络 client，且没有单个 doc/request 状态：

- `Settings` 启动期快照。
- SQLAlchemy `AsyncEngine`。
- `async_sessionmaker`。
- Redis client。
- MinIO client / `DocumentObjectStorage` wrapper。
- Kafka producer。
- MinerU `httpx.AsyncClient` / MinerU client wrapper。
- 图片总结 `ChatOpenAI`。
- 向量模型 `OpenAIEmbeddings`。
- Elasticsearch client / `ElasticsearchStore` 或 `AsyncElasticsearchStore`。

### 不应共享的资源

这些对象包含一次请求、一次消息、一个 doc、一个事务或一次调用的状态：

- `AsyncSession`。
- DB transaction。
- Redis lock 对象。
- Kafka message。
- Kafka consumer 之间的消费状态。
- 单个文档处理过程中的临时变量。
- 图片描述输入消息。
- embedding 输入的 `Document` 列表。
- 临时目录、临时文件。

一句话规则：

```text
池子共享，池子里借出来的使用上下文不共享。
客户端共享，单次请求 payload 不共享。
模型对象共享，单次调用输入不共享。
Redis client 共享，具体 lock 不共享。
```

## 模型与 ES store 调研结论

### ChatOpenAI

结论：可以作为 worker/runtime 级共享资源。

依据：

- 本地源码显示 `ChatOpenAI` 初始化后持有 `openai.OpenAI` 和 `openai.AsyncOpenAI` root client。
- OpenAI Python SDK 使用 `httpx` 同步/异步 client。
- HTTPX client 设计用于连接复用，不应在热路径里反复创建。

使用边界：

- 在 Kafka worker 的长期 event loop 中创建和使用。
- 如果 Celery 使用长期 async loop，也应在该 loop 中创建和使用。
- 不要把同一个 async client 跨多个 event loop 混用。

### OpenAIEmbeddings

结论：可以作为 vector runtime 级共享资源。

依据：

- 本地源码显示 `OpenAIEmbeddings` 初始化后持有 OpenAI embeddings client 和 async embeddings client。
- `aembed_documents()` 会复用 `self.async_client.create(...)`。

注意点：

- `OpenAIEmbeddings` 自身没有公开 `close/aclose`。
- 后续实现时更稳的方式是注入自管的 `httpx.Client` / `httpx.AsyncClient`，由 runtime 在 shutdown 时统一关闭。

### ElasticsearchStore

结论：可以作为 vector runtime 级共享资源，而且更应该共享。

依据：

- Elastic 官方 Python client 支持 persistent connections 和 thread safety across requests。
- 本地源码显示 `ElasticsearchStore` 构造时创建并保存 ES client，`close()` 会关闭底层 store/client。

重要发现：

- 当前项目创建的是同步 `ElasticsearchStore`。
- 但项目调用的是 `aadd_documents()`。
- LangChain 基类会把同步 `add_documents()` 丢进线程池执行，这不是真正的 async ES 写入。

倾向改进：

- 后续 runtime 治理时，考虑改用真正的 `AsyncElasticsearchStore`。
- 这样 embedding 和 ES 写入都在同一个 async runtime 下执行，模型更清晰。

## 拟进入 OpenSpec 的范围

建议新建 change：

```text
stabilize-process-runtime-lifecycle
```

建议包含：

1. API settings 启动期快照。
2. Kafka worker 进程级 runtime。
3. Celery worker async runtime 或补偿 runtime 分阶段治理。
4. 向量存储入口拆成 runtime 注入版：

```python
run_document_vector_storage_with_runtime(doc_id, runtime)
```

5. Kafka worker 和 Celery compensation 复用 runtime 注入版入口。
6. 老的 `run_document_vector_storage(doc_id)` 不再作为 worker 主路径。
7. 明确共享资源和短生命周期资源边界。
8. 保持“不补投 Kafka”和“不改变 Kafka commit 语义”。

## 待继续讨论的问题

1. Celery 本次是否直接做到进程级长期 async runtime？
   - 彻底方案：Celery signal + background asyncio loop。
   - 简化方案：每轮补偿任务初始化一次 runtime。

2. Kafka worker runtime 是否拆为多个 runtime？
   - 一个总的 `KafkaWorkerRuntime`。
   - 内含 `DocumentConversionRuntime` 和 `DocumentVectorStorageRuntime`。

3. 是否在本次同时把 `ElasticsearchStore` 换成 `AsyncElasticsearchStore`？
   - 优点：符合 async worker 模型。
   - 风险：改动范围变大，需要补测试。

4. `OpenAIEmbeddings` 和 `ChatOpenAI` 是否需要注入自管 HTTPX client？
   - 优点：关闭生命周期可控。
   - 风险：需要多写 runtime 管理和测试替身。

5. 是否需要为 OpenAI/ES 调用加并发限制？
   - 资源共享不等于无限并发。
   - 如果后续 worker 并发处理多个文档，可能需要 semaphore 或队列级并发限制。

6. 是否需要调整当前 `app.db.session` 的全局生命周期设计？
   - 当前全局 `_engine` / `_session_factory` 容易被多个 handler init/close 互相影响。
   - 可能需要让 init/close 只发生在进程入口，业务 handler 禁止调用。

## 暂定结论

本需求应作为 OpenSpec change 继续推进。

推荐设计方向：

```text
API
  -> FastAPI lifespan runtime
  -> settings 启动期快照

Kafka worker
  -> 原生 async worker runtime
  -> 启动期初始化 DB/Redis/MinIO/MinerU/ChatOpenAI/OpenAIEmbeddings/ES store

Celery worker
  -> 保留“不补投 Kafka”
  -> 通过 Celery signal + 长期 asyncio loop 支持启动期 runtime
  -> 或先按每轮补偿任务 runtime 过渡

Vector storage
  -> 拆 runtime 注入入口
  -> Kafka 和 Celery 共用业务处理逻辑
  -> per-doc 只创建 lock/session/transaction/payload
```

