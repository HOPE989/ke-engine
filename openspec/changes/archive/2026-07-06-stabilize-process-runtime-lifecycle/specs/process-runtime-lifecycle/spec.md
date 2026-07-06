## ADDED Requirements

### Requirement: Process-scoped runtime ownership
The system SHALL define runtime ownership by process type rather than by document ingestion stage.

#### Scenario: Runtime types are process-scoped
- **WHEN** the API process, Kafka worker process, or Celery worker child process initializes document ingestion resources
- **THEN** the API process SHALL initialize shared API resources in the FastAPI lifespan
- **AND** the API process SHALL expose startup settings through `application.state.settings`
- **AND** the API process SHALL expose document resources through `application.state.document_runtime`
- **AND** the Kafka worker process SHALL use a `KafkaWorkerRuntime`
- **AND** the Celery worker child process SHALL use a `CeleryWorkerRuntime`
- **AND** the system MUST NOT introduce separate lifecycle owners named for conversion, vector storage, or compensation stages

#### Scenario: Long-lived resources are runtime-owned
- **WHEN** a process runtime is initialized
- **THEN** it SHALL own that process's long-lived infrastructure resources
- **AND** those resources SHALL be released by the same runtime during process shutdown
- **AND** request handlers, Kafka message handlers, Celery tasks, and per-document workflows MUST NOT close runtime-owned resources

### Requirement: Startup-only infrastructure settings
The system SHALL treat infrastructure settings as startup-only settings for the process that owns the corresponding resources.

#### Scenario: Runtime captures settings snapshot
- **WHEN** a process runtime initializes
- **THEN** it SHALL capture one `Settings` snapshot
- **AND** long-lived resources SHALL be constructed from that snapshot
- **AND** later request, message, task, or document handling MUST NOT rebuild full infrastructure settings

#### Scenario: Configuration changes require restart
- **WHEN** database, Redis, Kafka, MinIO, MinerU, OpenAI, Elasticsearch, or embedding dimension configuration changes outside the process
- **THEN** the running process SHALL continue using its startup settings snapshot
- **AND** the new configuration SHALL take effect only after the relevant process is restarted

### Requirement: API lifespan resource lifecycle
The system SHALL initialize API process resources through the FastAPI lifespan and expose only startup settings plus module runtime state.

#### Scenario: API startup creates runtime resources
- **WHEN** the FastAPI lifespan starts
- **THEN** the system SHALL store the startup `Settings` snapshot on `application.state.settings`
- **AND** the system SHALL initialize a database session factory for lifespan-owned repositories
- **AND** the system SHALL initialize a `DocumentRuntime` on `application.state.document_runtime`
- **AND** `DocumentRuntime` SHALL include a Redis client
- **AND** `DocumentRuntime` SHALL include MinIO-backed document storage
- **AND** `DocumentRuntime` SHALL include a Kafka producer-backed conversion dispatcher
- **AND** `DocumentRuntime` SHALL include a Kafka producer-backed vector-storage dispatcher
- **AND** `DocumentRuntime` SHALL include the file detector
- **AND** `DocumentRuntime` SHALL include the document ID generator
- **AND** the API process MUST NOT expose a separate `application.state.api_runtime`

#### Scenario: API request reads runtime settings
- **WHEN** an API request needs configuration
- **THEN** the request SHALL read the startup settings snapshot from `application.state.settings`
- **AND** the request MUST NOT call a request-time full settings loader

#### Scenario: API shutdown releases runtime resources
- **WHEN** the FastAPI lifespan shuts down
- **THEN** the system SHALL release lifespan-owned resources
- **AND** the API process SHALL remove `settings` and `document_runtime` from application state

### Requirement: Kafka worker runtime lifecycle
The system SHALL initialize one `KafkaWorkerRuntime` for the Kafka worker process and share it across document ingestion consumers.

#### Scenario: Kafka worker startup creates shared runtime
- **WHEN** the Kafka worker process starts
- **THEN** the system SHALL initialize one `KafkaWorkerRuntime`
- **AND** `KafkaWorkerRuntime` SHALL include the startup `Settings` snapshot
- **AND** `KafkaWorkerRuntime` SHALL include a database session factory
- **AND** `KafkaWorkerRuntime` SHALL include a Redis client
- **AND** `KafkaWorkerRuntime` SHALL include MinIO-backed document storage
- **AND** `KafkaWorkerRuntime` SHALL include a MinerU client
- **AND** `KafkaWorkerRuntime` SHALL include an image summary chat model
- **AND** `KafkaWorkerRuntime` SHALL include an embedding model
- **AND** `KafkaWorkerRuntime` SHALL include an Elasticsearch vector store or client

#### Scenario: Kafka consumers share runtime resources
- **WHEN** the Kafka worker starts the document conversion consumer and document vector-storage consumer
- **THEN** both consumers SHALL receive or access the same `KafkaWorkerRuntime`
- **AND** both consumers SHALL use runtime-owned infrastructure resources on demand
- **AND** the consumers MUST NOT initialize or close database engines, Redis clients, MinerU clients, OpenAI models, or Elasticsearch stores inside message or document handling

#### Scenario: Kafka consumers keep independent consumption state
- **WHEN** the Kafka worker starts multiple document ingestion consumers
- **THEN** each Kafka consumer SHALL keep its own topic subscription, consumer group, polling state, and offset commit behavior
- **AND** sharing `KafkaWorkerRuntime` MUST NOT cause conversion and vector-storage consumers to share Kafka consumer instances

#### Scenario: Kafka worker shutdown releases runtime resources
- **WHEN** the Kafka worker process shuts down
- **THEN** the system SHALL close Kafka consumer instances
- **AND** the system SHALL release resources owned by `KafkaWorkerRuntime`

### Requirement: Celery worker runtime lifecycle
The system SHALL initialize one `CeleryWorkerRuntime` per Celery worker child process for document ingestion background tasks.

#### Scenario: Celery worker child startup creates runtime
- **WHEN** a Celery worker child process starts
- **THEN** the system SHALL create a long-lived asyncio event loop for that child process
- **AND** the system SHALL initialize one `CeleryWorkerRuntime` on that event loop
- **AND** `CeleryWorkerRuntime` SHALL include the startup `Settings` snapshot
- **AND** `CeleryWorkerRuntime` SHALL include a database session factory
- **AND** `CeleryWorkerRuntime` SHALL include a Redis client
- **AND** `CeleryWorkerRuntime` SHALL include MinIO-backed document storage
- **AND** `CeleryWorkerRuntime` SHALL include a MinerU client
- **AND** `CeleryWorkerRuntime` SHALL include an image summary chat model
- **AND** `CeleryWorkerRuntime` SHALL include an embedding model
- **AND** `CeleryWorkerRuntime` SHALL include an Elasticsearch vector store or client

#### Scenario: Celery task uses long-lived loop
- **WHEN** a scheduled document ingestion Celery task invokes async workflow logic
- **THEN** the task SHALL submit the coroutine to the child process's long-lived asyncio loop
- **AND** the task MUST NOT create a new event loop with `asyncio.run()` for each task execution

#### Scenario: Celery worker child shutdown releases runtime
- **WHEN** a Celery worker child process shuts down
- **THEN** the system SHALL release resources owned by `CeleryWorkerRuntime`
- **AND** the system SHALL stop and close the child process's long-lived asyncio event loop

### Requirement: Runtime-injected vector storage execution
The system SHALL run document vector storage through a runtime-injected entrypoint shared by Kafka and Celery callers.

#### Scenario: Kafka vector storage uses runtime-injected entrypoint
- **WHEN** the Kafka vector-storage consumer handles a vector-storage event
- **THEN** it SHALL call a vector-storage function that receives the worker runtime
- **AND** the vector-storage function SHALL use the runtime-owned database session factory, Redis client, embedding model, and Elasticsearch vector store or client
- **AND** the Kafka handler SHALL continue to use the function result to decide whether to commit the consumed Kafka message

#### Scenario: Celery compensation uses runtime-injected entrypoint
- **WHEN** Celery compensation processes a stale `CHUNKED` document
- **THEN** it SHALL call the same runtime-injected vector-storage business function
- **AND** it SHALL use resources owned by `CeleryWorkerRuntime`
- **AND** it MUST NOT publish a Kafka event for that document
- **AND** it MUST NOT call a function whose responsibility includes committing Kafka offsets

#### Scenario: Legacy non-injected vector storage is not the main worker path
- **WHEN** Kafka worker or Celery compensation performs vector storage
- **THEN** the main execution path MUST NOT use a vector-storage entrypoint that initializes and closes infrastructure resources internally for each document

### Requirement: Short-lived operation contexts
The system SHALL keep per-operation state out of process runtimes.

#### Scenario: Request and worker operations create short-lived contexts
- **WHEN** the system handles an API request, Kafka message, Celery task, or document workflow
- **THEN** it SHALL create database sessions only for the operation or transaction scope
- **AND** it SHALL create Redis lock objects only for the specific document operation
- **AND** it SHALL create Kafka message objects, delivery futures, segment batches, LangChain document inputs, temporary directories, and temporary files only for the operation that needs them
- **AND** it MUST NOT store those short-lived contexts as reusable process runtime resources

### Requirement: Existing ingestion semantics are preserved
The runtime lifecycle change SHALL NOT alter document ingestion business semantics.

#### Scenario: Kafka commit semantics are unchanged
- **WHEN** the Kafka vector-storage consumer processes a message
- **THEN** terminal outcomes SHALL still be eligible for Kafka commit
- **AND** retryable vector-storage failures SHALL still leave the message uncommitted
- **AND** only the Kafka message handler SHALL own Kafka offset commit behavior

#### Scenario: Celery compensation remains direct
- **WHEN** Celery compensation finds stale `CHUNKED` documents
- **THEN** it SHALL process those documents directly with runtime-owned resources
- **AND** it MUST NOT redispatch those documents to Kafka

#### Scenario: Public API and Kafka contracts remain stable
- **WHEN** this change is implemented
- **THEN** existing public API routes SHALL keep their external request and response contracts
- **AND** Kafka topic names, consumer group names, and event payload shapes SHALL remain unchanged
