## Context

The document ingestion path now spans three process types:

- FastAPI serves document upload, chunking, and manual vector-storage dispatch endpoints.
- The Kafka worker runs the document conversion consumer and the document vector-storage consumer in the same Python process and event loop.
- The Celery worker runs scheduled compensation for stale `CHUNKED` documents.

The API side needs one FastAPI lifespan resource initializer that stores startup settings and assembles module runtime state. Kafka and Celery still create expensive infrastructure resources inside hot paths. The most important correctness issue is the shared module-level database engine/session factory: Kafka conversion and vector-storage consumers can both call `init_engine()` and `close_engine()` while running concurrently in the same process.

Configuration is startup-only for infrastructure resources. Changing database, Redis, Kafka, MinIO, MinerU, OpenAI, Elasticsearch, or embedding dimension settings requires restarting the relevant process.

## Goals / Non-Goals

**Goals:**

- Define API resource ownership through the FastAPI lifespan, with module-scoped application state such as `DocumentRuntime`.
- Define one worker runtime per worker process type: `KafkaWorkerRuntime` and `CeleryWorkerRuntime`.
- Initialize long-lived infrastructure resources once during process startup and release them once during process shutdown.
- Keep request, message, task, document, transaction, and lock contexts short-lived.
- Make Kafka conversion and vector-storage consumers share one `KafkaWorkerRuntime` instead of initializing separate resource groups.
- Make Celery compensation use one `CeleryWorkerRuntime` and a long-lived asyncio loop owned by the Celery worker child process.
- Refactor vector storage so Kafka and Celery callers reuse the same runtime-injected business logic.
- Preserve Kafka commit behavior, Kafka topics/groups/payloads, and Celery's direct compensation model.

**Non-Goals:**

- No new public API route behavior.
- No Kafka topic, consumer group, event payload, or offset commit semantic changes.
- No Celery compensation redispatch to Kafka.
- No retrieval, chat, document versioning, dead-letter queue, or vector search behavior changes.
- No runtime hot reload for infrastructure settings.

## Decisions

### Decision 1: Runtime boundaries follow process and module state

Use FastAPI lifespan ownership for API resources, and module-scoped state for API modules:

```text
application.state.settings
application.state.document_runtime
KafkaWorkerRuntime
CeleryWorkerRuntime
```

Do not introduce an API-wide `api_runtime` state object when the only shared API value is the startup settings snapshot. When future API modules are added, they should receive their own module runtime state, for example `application.state.chat_runtime`.

Do not split Kafka or Celery resources into `conversion`, `vector`, or `compensation` runtimes. Those are business usages, not lifecycle owners. A worker process starts to serve the whole document ingestion worker role, so it initializes the resources that role can need and each code path takes only the resources it uses.

Alternative considered: separate conversion/vector/compensation runtimes. This was rejected because it duplicates ownership decisions, encourages partial init/close inside business stages, and does not match how the worker processes are actually started.

### Decision 2: API requests read settings from application state

Store the startup `Settings` snapshot on `application.state.settings`. API dependencies read settings from application state rather than reconstructing full settings per request.

This makes configuration semantics explicit: infrastructure settings are startup-only, and request handlers observe the same settings that were used to initialize DB, Redis, MinIO, Kafka producer, and dispatchers.

Alternative considered: store settings on an API-wide `ApiRuntime`. This was rejected because it creates a redundant API runtime state object only to carry settings, while module resources already have clear module-specific state names.

### Decision 3: Database engine/session factory are runtime-owned

Each process runtime owns DB engine initialization and shutdown. Business handlers must not call `init_engine()` or `close_engine()`.

`async_sessionmaker` is a long-lived runtime resource. `AsyncSession` and transactions remain short-lived and are created per repository operation or per business transaction.

This removes the Kafka worker race where two consumers share module-level DB state but independently initialize and close it.

### Decision 4: Worker long-lived resources are initialized together and used on demand

`KafkaWorkerRuntime` owns:

- startup `Settings` snapshot
- DB engine/session factory
- Redis client
- MinIO client and document storage wrapper
- MinerU client
- image summary chat model
- embedding model
- Elasticsearch vector store/client

The conversion consumer uses DB, Redis, MinIO, MinerU, and the image model. The vector-storage consumer uses DB, Redis, embedding, and Elasticsearch resources. Both consumers share the same runtime; Kafka consumer instances remain separate because topic/group/offset state is consumer-specific.

`CeleryWorkerRuntime` owns the same document-processing infrastructure resources plus the long-lived asyncio loop required to run async business logic from synchronous Celery tasks.

### Decision 5: Vector storage gets a runtime-injected entrypoint

Introduce a runtime-injected vector storage entrypoint, conceptually:

```python
run_document_vector_storage_with_runtime(doc_id, runtime)
```

Kafka message handlers call this function and use its boolean result for commit decisions. Celery compensation calls the same function for stale `CHUNKED` documents but does not perform any Kafka commit or redispatch behavior.

The existing non-injected entrypoint must not remain the Kafka or Celery main path if it initializes infrastructure resources internally.

### Decision 6: Async clients stay on their owning event loop

Async resources created by worker runtimes, including MinerU HTTP clients and OpenAI/LangChain async clients, must be created and used on the same long-lived event loop.

Kafka naturally runs inside its worker event loop. Celery requires worker-process lifecycle hooks to create a background loop, initialize `CeleryWorkerRuntime` on that loop, submit task coroutines to it, and shut it down during worker process shutdown.

### Decision 7: Shutdown is centralized and best-effort ordered

Runtime constructors register cleanup for resources that expose `close`, `aclose`, `dispose`, or equivalent shutdown methods. Shutdown should release resources in reverse creation order where that matters, especially async clients and DB engines.

Business handlers must not close runtime-owned clients.

## Risks / Trade-offs

- Runtime startup can fail earlier when configuration for a worker-owned resource is invalid or missing. -> This is acceptable because infrastructure configuration is startup-only; fail-fast is clearer than failing on the first document.
- Celery prefork creates multiple child processes. -> Runtime initialization must happen in each child process, not in the parent before fork.
- Celery's synchronous task API must call async code safely. -> Use a long-lived child-process event loop and submit coroutines to it; do not call `asyncio.run()` per task.
- Sharing model and Elasticsearch clients can increase concurrent pressure if worker concurrency grows. -> Keep the design compatible with runtime-owned semaphores or queue-level concurrency limits, but preserve current processing semantics unless concurrency is explicitly changed.
- Some third-party wrappers do not expose obvious close hooks. -> Runtime shutdown must close the underlying client when available and tests should cover known resources.
