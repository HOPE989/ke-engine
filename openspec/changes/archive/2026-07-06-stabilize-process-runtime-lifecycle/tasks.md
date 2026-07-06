## 1. Runtime Foundation

- [x] 1.1 Add or update tests that assert runtime ownership is process-scoped: FastAPI lifespan resources, `KafkaWorkerRuntime`, and `CeleryWorkerRuntime`.
- [x] 1.2 Introduce shared runtime construction helpers for long-lived resource cleanup using explicit close/aclose/dispose callbacks.
- [x] 1.3 Ensure database engine and session factory initialization can be owned by process runtimes without business handlers calling `init_engine()` or `close_engine()`.
- [x] 1.4 Add tests that fail if Kafka or Celery document handlers initialize or close DB engine resources inside message/task/document execution paths.

## 2. API Lifespan and Document Runtime State

- [x] 2.1 Define document API resources as `DocumentRuntime` module state and update imports, dependencies, and tests.
- [x] 2.2 Store the startup `Settings` snapshot on `application.state.settings`.
- [x] 2.3 Change API configuration dependency logic so requests read settings from application state instead of rebuilding full settings per request.
- [x] 2.4 Keep API-owned DB, Redis, MinIO, Kafka producer dispatchers, Magika, and Snowflake resources initialized during FastAPI lifespan and released during shutdown.
- [x] 2.5 Update API tests to verify request-time configuration no longer calls the full request settings loader.

## 3. Kafka Worker Runtime

- [x] 3.1 Add `KafkaWorkerRuntime` with startup settings, DB session factory, Redis client, MinIO-backed storage, MinerU client, image chat model, embedding model, and Elasticsearch vector store/client.
- [x] 3.2 Make `KafkaWorkerRuntime` initialize all long-lived worker resources once during worker startup and release them during worker shutdown.
- [x] 3.3 Update `app.workers.kafka_worker` so conversion and vector-storage consumers receive or access the same `KafkaWorkerRuntime`.
- [x] 3.4 Keep Kafka consumer instances separate per topic/group while sharing the runtime for infrastructure resources.
- [x] 3.5 Update Kafka worker host tests to verify one shared runtime is created and both consumers are started with it.

## 4. Kafka Conversion Path

- [x] 4.1 Refactor document conversion worker functions to accept `KafkaWorkerRuntime`.
- [x] 4.2 Replace per-message Redis client creation with runtime-owned Redis client usage while keeping Redis lock objects per document.
- [x] 4.3 Replace per-message DB engine init/close with runtime-owned session factory usage while keeping `AsyncSession` short-lived.
- [x] 4.4 Replace lazy per-message MinIO storage, MinerU client, and image chat model construction with runtime-owned resources.
- [x] 4.5 Update conversion worker tests to verify conversion messages do not initialize or close runtime-owned resources.

## 5. Kafka Vector Storage Path

- [x] 5.1 Add a runtime-injected vector storage entrypoint used by worker callers.
- [x] 5.2 Refactor Kafka vector-storage consumer and message handler to pass `KafkaWorkerRuntime` through to vector storage execution.
- [x] 5.3 Replace per-document Redis client, embedding model, and Elasticsearch store construction with runtime-owned resources while keeping Redis locks per document.
- [x] 5.4 Preserve existing vector-storage commit decisions for terminal, successful, busy-lock, and retryable failure outcomes.
- [x] 5.5 Update vector-storage worker tests to verify Kafka commit semantics are unchanged and per-document resource initialization is removed.

## 6. Celery Worker Runtime

- [x] 6.1 Add `CeleryWorkerRuntime` with startup settings, DB session factory, Redis client, MinIO-backed storage, MinerU client, image chat model, embedding model, and Elasticsearch vector store/client.
- [x] 6.2 Add Celery worker-process lifecycle hooks that create a child-process long-lived asyncio loop and initialize `CeleryWorkerRuntime` on that loop.
- [x] 6.3 Change scheduled compensation task execution to submit async workflow work to the long-lived loop instead of calling `asyncio.run()` per task.
- [x] 6.4 Refactor stale `CHUNKED` document scanning to use `CeleryWorkerRuntime` database resources without task-local DB engine init/close.
- [x] 6.5 Refactor compensation vector storage processing to call the runtime-injected vector storage entrypoint without publishing Kafka messages or touching Kafka commit logic.
- [x] 6.6 Add Celery shutdown handling that releases `CeleryWorkerRuntime` resources and stops/closes the child-process event loop.
- [x] 6.7 Update Celery tests to verify compensation does not call `asyncio.run()`, does not redispatch Kafka events, and does not initialize resources per document.

## 7. Cleanup and Verification

- [x] 7.1 Remove old worker hot-path resource initialization helpers that are no longer used by Kafka or Celery main paths.
- [x] 7.2 Keep any legacy non-injected vector storage entrypoint out of Kafka and Celery main execution paths, or remove it if no supported caller remains.
- [x] 7.3 Update resource ownership tests and documentation comments to reflect API lifespan resources, `KafkaWorkerRuntime`, and `CeleryWorkerRuntime`.
- [x] 7.4 Run the targeted backend tests covering API runtime, Kafka worker host, conversion worker, vector-storage worker, and Celery compensation.
- [x] 7.5 Run OpenSpec validation/status checks for `stabilize-process-runtime-lifecycle`.

## 8. Review Follow-up Runtime Boundaries

- [x] 8.1 Add tests proving Kafka and Celery worker runtimes expose process-specific typed contexts without adding stage lifecycle owners.
- [x] 8.2 Split Kafka and Celery worker runtime construction so they do not share a cross-worker runtime aggregation helper.
- [x] 8.3 Move Kafka worker cleanup stack ownership into the Kafka worker host and remove the runtime-module Kafka context manager.

## 9. Review Follow-up Runtime Module Placement

- [x] 9.1 Add tests proving `app.runtime` is removed and runtime owners live in `app.api.deps`, `app.workers.kafka_worker`, and `app.workers.celery_worker`.
- [x] 9.2 Move API runtime dataclass and API resource stack/database lifecycle helpers into `app.api.deps`.
- [x] 9.3 Move Kafka worker runtime dataclasses, context views, resource stack, image describer, and construction helpers into `app.workers.kafka_worker`.
- [x] 9.4 Move Celery worker runtime dataclasses, context views, resource stack, image describer, and construction helpers into `app.workers.celery_worker`.
- [x] 9.5 Delete `backend/app/runtime.py` and update all runtime type imports to process-owner modules.

## 10. Review Follow-up API Lifespan Naming

- [x] 10.1 Add tests proving the API process lifespan initializer assembles document module resources through `application.state.document_runtime`.
- [x] 10.2 Change request configuration access to read startup settings from lifespan-owned application state.
- [x] 10.3 Update FastAPI lifespan wiring to initialize API resources and assemble document runtime state in the same initialization flow.

## 11. Review Follow-up Module Runtime State

- [x] 11.1 Add tests proving the API lifespan stores startup settings on `application.state.settings` and exposes only module runtimes such as `application.state.document_runtime`.
- [x] 11.2 Remove the `api_runtime`/`ApiRuntime` state layer from API dependencies while keeping document resources assembled during the same lifespan initialization.
- [x] 11.3 Update FastAPI wiring and OpenSpec artifacts to describe module-scoped runtime state instead of a separate API runtime state object.

## 12. Review Follow-up Type Checking Imports

- [x] 12.1 Add tests proving worker `TYPE_CHECKING` imports document why they avoid runtime imports.
- [x] 12.2 Add Chinese comments to worker `TYPE_CHECKING` imports explaining circular dependency prevention.
