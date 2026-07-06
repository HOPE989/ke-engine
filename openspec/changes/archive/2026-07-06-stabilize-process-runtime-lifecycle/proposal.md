## Why

The RAG ingestion path currently creates and closes expensive infrastructure resources inside request, Kafka message, Celery task, or per-document execution paths. This adds avoidable latency and, in the Kafka worker, creates a correctness risk because concurrent consumers share the same module-level database engine/session factory while independently calling init and close.

The system needs one clear resource lifecycle model: initialize long-lived resources at process startup, create only lightweight operation context during request/message/task handling, and release long-lived resources during process shutdown.

## What Changes

- Keep API resource initialization in the FastAPI lifespan and store the startup `Settings` snapshot on `application.state.settings`.
- Assemble API module resources as module-scoped state, currently `application.state.document_runtime`, so future modules can add their own `<module>_runtime` without a redundant API-wide runtime object.
- Stop rebuilding full infrastructure settings during API requests; request handlers read the startup settings snapshot from application state.
- Introduce one `KafkaWorkerRuntime` for the Kafka worker process, shared by the conversion consumer and vector-storage consumer.
- Initialize Kafka worker long-lived resources once at worker startup, including database engine/session factory, Redis client, MinIO storage, MinerU client, image summary model, embedding model, and Elasticsearch vector store/client.
- Keep Kafka consumers separate per topic/group, while having both consumers use the shared `KafkaWorkerRuntime` for infrastructure resources.
- Introduce one `CeleryWorkerRuntime` per Celery worker child process, including a long-lived asyncio loop and the same document-processing infrastructure resources needed by scheduled compensation work.
- Refactor vector storage execution to accept a process runtime so Kafka worker and Celery compensation can reuse the same business logic without reinitializing resources per document.
- Preserve existing business semantics: Celery compensation does not publish Kafka messages, Kafka commit decisions remain owned only by Kafka message handlers, and per-request/per-message/per-document contexts remain short-lived.

## Capabilities

### New Capabilities
- `process-runtime-lifecycle`: Defines process-level runtime ownership and resource lifecycle rules for API, Kafka worker, and Celery worker processes.

### Modified Capabilities

None.

## Impact

- Affected API code: `app.main`, `app.api.deps`, module runtime dataclasses, document API dependencies, and tests that reference `DocumentRuntime`.
- Affected Kafka worker code: `app.workers.kafka_worker`, document conversion worker, document vector-storage worker, DB session lifecycle usage, and worker lifecycle tests.
- Affected Celery worker code: `app.workers.celery_worker`, Celery app/task initialization, document vector-storage compensation task, and Celery worker tests.
- Affected infrastructure code: database session lifecycle management, Redis/MinIO/MinerU/OpenAI/Elasticsearch resource construction and shutdown, vector store adapter construction.
- No API route contract changes are intended.
- No Kafka topic, event payload, consumer group, or commit semantic changes are intended.
- No Celery compensation behavior change is intended beyond resource lifecycle and avoiding per-document resource initialization.
