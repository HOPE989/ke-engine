# Kafka Document Workers Design

## Context

The current document upload flow uses Celery with Redis as the broker. After the API uploads the original document and marks it as `UPLOADED`, it dispatches a `document.convert` Celery task. The worker then acquires a Redis document lock and calls the existing document conversion workflow.

We will migrate away from Celery and use native Kafka messaging because Kafka is the team's shared message infrastructure. The first implementation targets local self-hosted Kafka for development, while keeping the configuration shape compatible with later departmental Kafka access.

## Goals

- Remove Celery from the document conversion dispatch and worker path.
- Use `confluent-kafka` as the native Kafka client.
- Keep document worker business logic inside the document module.
- Support one Python worker process hosting one or more async consumer runners.
- Keep slow or blocking work from blocking unrelated consumer runners in the same event loop.
- Preserve idempotency and duplicate-consumption protection.

## Non-Goals

- Do not use Celery over Kafka.
- Do not design department-cluster authentication in this first step.
- Do not introduce a full workflow engine.
- Do not migrate future embedding, indexing, or cleanup workers yet.

## Package Choice

Use:

```toml
"confluent-kafka>=2.15.0,<3.0.0"
```

Rationale:

- It is the official Confluent Python client and is backed by `librdkafka`.
- It supports producer, consumer, admin, manual offset commit, and advanced Kafka options.
- It is a better match for a native Kafka architecture than keeping Celery semantics and only changing the broker.
- The project can use the AsyncIO client for worker runners because the document conversion path already uses async database and HTTP operations.

## Architecture

```text
FastAPI upload request
  -> validate and store original document
  -> DB status: INIT -> UPLOADED
  -> Kafka producer sends document.convert.requested

Kafka worker process
  -> one asyncio event loop
  -> one or more consumer runner tasks
  -> document conversion runner consumes document.convert.requested
  -> handler calls existing convert_uploaded_document()
  -> success commits Kafka offset
```

The global worker process is only a host. It should not contain document business logic.

```text
backend/app/workers/kafka_worker.py
  Starts enabled consumer runners.

backend/app/modules/document/workers/conversion.py
  Owns document conversion consumer logic.
```

## File Layout

Recommended first-step layout:

```text
backend/app/infrastructure/kafka.py
  Kafka producer and consumer factory helpers.

backend/app/modules/document/events.py
  DocumentConvertRequested event schema and serialization helpers.

backend/app/modules/document/dispatcher.py
  KafkaDocumentConversionDispatcher used by the upload workflow.

backend/app/modules/document/workers/__init__.py
  Document worker package marker.

backend/app/modules/document/workers/conversion.py
  run_document_conversion_consumer()
  handle_document_conversion_event()
  run_document_conversion()

backend/app/workers/__init__.py
  Worker entrypoint package marker.

backend/app/workers/kafka_worker.py
  Async process entrypoint that starts configured consumer runners.
```

The existing `backend/app/modules/document/tasks.py` should be removed or reduced to compatibility only during migration. It should not remain the primary worker abstraction after Celery is removed, because `tasks.py` implies Celery-style task semantics.

## Event Shape

Topic:

```text
document.convert.requested
```

Consumer group:

```text
ke-engine-document-converter
```

Message key:

```text
doc_id as string
```

Payload:

```json
{
  "event_id": "uuid-or-generated-id",
  "event_type": "document.convert.requested",
  "doc_id": "123456789",
  "occurred_at": "2026-07-02T00:00:00Z"
}
```

`doc_id` remains the durable business identifier. `event_id` supports logging, tracing, and later duplicate-event diagnostics. The first implementation can generate it with UUID.

## Producer Flow

The upload workflow keeps its current durable ordering:

```text
1. Create INIT document row.
2. Upload original object to MinIO.
3. Mark document as UPLOADED.
4. Produce document.convert.requested to Kafka.
5. Return 202 response.
```

If Kafka produce fails after the original document is stored and the row is `UPLOADED`, the API should keep the current behavior style: log the failure and still return the upload response. The document remains `UPLOADED`. A later repair or retry mechanism can re-emit conversion events for stale uploaded documents.

## Consumer Flow

The document conversion runner should:

```text
1. Poll Kafka for document.convert.requested.
2. Deserialize and validate the event.
3. Acquire the existing per-document Redis lock.
4. Initialize runtime resources needed by conversion.
5. Call convert_uploaded_document().
6. Commit the Kafka offset only after successful handling.
7. Close per-run resources cleanly on shutdown.
```

The existing Redis lock can remain in the first Kafka version. Kafka provides delivery and partition ordering, but it does not remove the need for application-level idempotency when messages are duplicated, retried, or manually re-emitted.

## Worker Host Model

The worker host may run multiple consumer runners in one process:

```python
async def main():
    async with asyncio.TaskGroup() as tg:
        tg.create_task(run_document_conversion_consumer())
```

The structure allows future runners:

```python
async def main():
    async with asyncio.TaskGroup() as tg:
        tg.create_task(run_document_conversion_consumer())
        tg.create_task(run_document_embedding_consumer())
        tg.create_task(run_document_indexing_consumer())
```

Each runner should own its own Kafka consumer instance. Avoid one consumer subscribing to unrelated business topics, because a slow handler in one topic can block polling and processing for the others.

Deployment can still split heavy runners into separate processes or containers. The code supports shared hosting, while deployment chooses the isolation level.

## Async and Blocking Work

The worker process uses one asyncio event loop, similar to Uvicorn's concurrency model. Long-lived consumer loops are scheduled as tasks.

Rules:

- Async DB and HTTP calls should stay as normal `await` operations.
- Blocking file IO, ZIP extraction, synchronous SDK calls, or medium CPU work should run via `starlette.concurrency.run_in_threadpool` or `asyncio.to_thread`.
- Document conversion should have a concurrency limit, such as an `asyncio.Semaphore`, so one worker process does not start unbounded PDF conversions.
- If conversion becomes CPU-heavy or memory-heavy, deploy document conversion as a separate worker role.

## Offset Commit and Failure Handling

Use manual commit:

```text
enable.auto.commit = false
```

Commit only after successful event handling.

First-step failure behavior:

- Validation failure: log with event metadata and commit, because the message is not processable.
- Transient conversion failure: do not commit, allowing Kafka redelivery after restart or rebalance.
- Lock busy: treat as a successful no-op and commit, because another worker is already processing the same document.

Retry topics and dead-letter topics are useful but not required in the first migration. They can be introduced after the basic Kafka path is stable.

## Configuration

Add settings similar to:

```text
KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:9092
KAFKA_DOCUMENT_CONVERT_TOPIC=document.convert.requested
KAFKA_DOCUMENT_CONVERT_GROUP_ID=ke-engine-document-converter
KAFKA_WORKER_CONSUMERS=document_convert
DOCUMENT_CONVERT_CONCURRENCY=1
```

`KAFKA_WORKER_CONSUMERS` controls which runners the shared worker host starts. First implementation enables only `document_convert`.

## Local Development

`docker-compose.yml` should add a self-hosted Kafka service for local development. The Makefile should replace the Celery worker command with a Kafka worker command:

```text
make dev-worker
  cd backend && uv run python -m app.workers.kafka_worker
```

`make dev-infra` should start the lightweight backend infrastructure needed for upload and conversion, including Kafka after migration.

## Testing Strategy

Unit tests should cover:

- Kafka event serialization and validation.
- Dispatcher sends the expected topic, key, and payload.
- Upload workflow logs and continues when dispatch fails.
- Conversion consumer commits after successful handling.
- Conversion consumer does not commit on transient conversion failure.
- Busy document lock is treated as a no-op success.
- Worker host starts only configured runners.

Integration tests with a real Kafka container can be added later. The first migration should keep Kafka client calls behind small interfaces so core behavior remains unit-testable without Kafka.

## Migration Steps

1. Add Kafka configuration and dependency.
2. Add local Kafka service to Docker Compose.
3. Add Kafka producer and consumer helpers.
4. Add document event schema.
5. Replace Celery dispatcher with Kafka dispatcher.
6. Add document conversion consumer runner.
7. Add global Kafka worker host entrypoint.
8. Update Makefile and environment examples.
9. Remove Celery dependency and Celery-specific configuration after tests pass.

## Design Decision

Proceed with native Kafka using `confluent-kafka`. Keep business worker logic inside module-local `workers/` packages, with a thin global worker host for process startup. First migration scope is only document conversion.
