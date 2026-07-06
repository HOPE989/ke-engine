## ADDED Requirements

### Requirement: Document vector storage trigger endpoint
The system SHALL expose a manual vector-storage trigger endpoint at `POST /api/v1/document/{doc_id}/embed-store` for end-to-end testing and explicit retry.

#### Scenario: Chunked document dispatches vector storage
- **WHEN** a client requests vector storage for an existing document whose status is `CHUNKED`
- **THEN** the system SHALL publish a `document.embed_store.requested` Kafka event for that document
- **AND** the system SHALL return a success response without performing embedding or Elasticsearch writes in the request

#### Scenario: Manual dispatch failure is reported
- **WHEN** a client requests vector storage for an existing document whose status is `CHUNKED`
- **AND** Kafka event production, flush, or delivery acknowledgement fails
- **THEN** the system SHALL return HTTP 503 with `APIResponse.code` equal to `503`
- **AND** the response message SHALL be `vector storage dispatch failed`
- **AND** the system MUST NOT perform embedding or Elasticsearch writes in the request

#### Scenario: Missing document is rejected
- **WHEN** a client requests vector storage for a `doc_id` that does not exist
- **THEN** the system SHALL return HTTP 404 with `APIResponse.code` equal to `404`
- **AND** the response message SHALL be `document not found`
- **AND** the system MUST NOT publish a vector-storage Kafka event

#### Scenario: Non-chunked document is rejected
- **WHEN** a client requests vector storage for a document whose status is not `CHUNKED` or `VECTOR_STORED`
- **THEN** the system SHALL return HTTP 409 with `APIResponse.code` equal to `409`
- **AND** the response message SHALL be `document state conflict`
- **AND** the system MUST NOT publish a vector-storage Kafka event

#### Scenario: Already vector-stored document is idempotent
- **WHEN** a client requests vector storage for a document whose status is `VECTOR_STORED`
- **THEN** the system SHALL return a success response
- **AND** the system MUST NOT publish a duplicate vector-storage Kafka event

### Requirement: Document vector storage Kafka event
The system SHALL represent document vector-storage work as a typed Kafka event.

#### Scenario: Vector storage event shape
- **WHEN** the system creates a document vector-storage event
- **THEN** the event payload SHALL include `event_id`
- **AND** the event payload SHALL include `event_type` equal to `document.embed_store.requested`
- **AND** the event payload SHALL include `doc_id` serialized as a string
- **AND** the event payload SHALL include `occurred_at` as an ISO-8601 UTC timestamp ending with `Z`

#### Scenario: Vector storage dispatcher publishes to Kafka
- **WHEN** the document vector-storage dispatcher sends an event
- **THEN** it SHALL publish to topic `document.embed_store.requested`
- **AND** it SHALL use the document id as the Kafka message key
- **AND** it SHALL flush the producer before the API trigger reports dispatch success

### Requirement: Chunking vector storage dispatch
The system SHALL dispatch vector storage after successful document chunking.

#### Scenario: Successful chunking dispatches vector storage event
- **WHEN** document chunking commits generated segments and advances a document to `CHUNKED`
- **THEN** the system SHALL publish a `document.embed_store.requested` Kafka event for that document
- **AND** the event SHALL be published only after chunking persistence succeeds

#### Scenario: Failed chunking does not dispatch vector storage event
- **WHEN** document chunking fails before the document reaches `CHUNKED`
- **THEN** the system MUST NOT publish a `document.embed_store.requested` Kafka event for that document

### Requirement: Document vector storage worker lifecycle
The system SHALL run a Kafka consumer that processes document vector-storage events and uses explicit commit rules for terminal and retryable outcomes.

#### Scenario: Worker subscribes to vector storage topic
- **WHEN** the worker process starts
- **THEN** it SHALL subscribe to topic `document.embed_store.requested`
- **AND** it SHALL use consumer group id `ke-engine-document-embed-store`

#### Scenario: Successful vector storage commits Kafka message
- **WHEN** a vector-storage message is processed successfully through document completion
- **THEN** the worker SHALL commit the consumed Kafka message

#### Scenario: Missing document commits Kafka message
- **WHEN** the worker receives an event for a `doc_id` that does not exist
- **THEN** it SHALL treat the message as terminal and non-actionable
- **AND** it SHALL NOT create Elasticsearch vectors
- **AND** it SHALL commit the consumed Kafka message

#### Scenario: Already vector-stored document commits Kafka message
- **WHEN** the worker receives an event for a document whose status is `VECTOR_STORED`
- **THEN** it SHALL treat the document as already complete
- **AND** it SHALL NOT create additional Elasticsearch vectors
- **AND** it SHALL commit the consumed Kafka message

#### Scenario: Invalid document business state commits Kafka message
- **WHEN** the worker receives an event for a document whose status is not `CHUNKED` or `VECTOR_STORED`
- **THEN** it SHALL treat the message as terminal for this worker
- **AND** it SHALL NOT create Elasticsearch vectors
- **AND** it SHALL commit the consumed Kafka message

#### Scenario: Busy vector storage lock skips processing
- **WHEN** another worker already holds the vector-storage lock for the same document
- **THEN** the worker SHALL NOT process that document concurrently
- **AND** the worker SHALL leave the message uncommitted for retry

#### Scenario: Retryable vector storage failure does not commit Kafka message
- **WHEN** vector storage fails because of OpenAI, Elasticsearch, Redis, database, vector ID count mismatch, cleanup, or double-check failure
- **THEN** the worker SHALL NOT commit the consumed Kafka message
- **AND** the failure SHALL remain retryable by Kafka delivery

### Requirement: Vector storage preconditions
The system SHALL only run embedding and Elasticsearch storage for existing `CHUNKED` documents.

#### Scenario: Chunked document enters vector storage
- **WHEN** the worker receives an event for an existing document whose status is `CHUNKED`
- **THEN** it SHALL run the vector-storage workflow for that document
- **AND** it SHALL acquire a Redis lock named `document:{doc_id}:embed-store` before processing begins

### Requirement: Embedding model configuration
The system SHALL use an OpenAI-compatible LangChain embedding model with stable batch and dimension behavior.

#### Scenario: Embedding model uses configured provider connection
- **WHEN** the vector-storage worker creates the embedding model
- **THEN** it SHALL use `OPENAI_API_KEY` for the API key
- **AND** it SHALL use `OPENAI_BASE_URL` when that value is configured
- **AND** it SHALL use model `text-embedding-v4`

#### Scenario: Embedding request chunk size is fixed
- **WHEN** the vector-storage worker creates `OpenAIEmbeddings`
- **THEN** it SHALL set `chunk_size` to `9`
- **AND** this value SHALL NOT be read from runtime settings

#### Scenario: Embedding dimensions are configurable
- **WHEN** the vector-storage worker creates `OpenAIEmbeddings`
- **THEN** it SHALL set `dimensions` from `Settings.embedding_dimensions`
- **AND** the default `embedding_dimensions` SHALL be `1536`
- **AND** the environment variable alias SHALL be `EMBEDDING_DIMENSIONS`

#### Scenario: Non-native model tokenizer guard is disabled
- **WHEN** the vector-storage worker creates `OpenAIEmbeddings`
- **THEN** it SHALL set `check_embedding_ctx_length` to `False`

### Requirement: Elasticsearch vector store configuration
The system SHALL write vector documents to a configured Elasticsearch index.

#### Scenario: Elasticsearch settings are available
- **WHEN** backend settings are loaded
- **THEN** `Settings.elasticsearch_url` SHALL be available
- **AND** `Settings.elasticsearch_index` SHALL be available
- **AND** `Settings.embedding_dimensions` SHALL be available

#### Scenario: Elasticsearch index defaults are stable
- **WHEN** no explicit Elasticsearch index is configured
- **THEN** the system SHALL use `ke-engine-vector` as the vector index name

#### Scenario: Elasticsearch vector mapping matches embedding dimensions
- **WHEN** the vector-storage infrastructure prepares or validates the target index
- **THEN** the vector field dimensions SHALL equal `Settings.embedding_dimensions`

#### Scenario: Vector store dependency is available
- **WHEN** backend dependencies are installed
- **THEN** the `langchain-elasticsearch` Python package SHALL be available for Elasticsearch vector storage

### Requirement: Vector document payload
The system SHALL store each embeddable segment as a vector document with separate page content and metadata.

#### Scenario: Segment text is stored as page content
- **WHEN** the worker writes a `KnowledgeSegment` to Elasticsearch
- **THEN** it SHALL use `knowledge_segment.text` as the vector document page content
- **AND** it MUST NOT duplicate the segment text into the metadata payload

#### Scenario: Segment metadata is stored as vector metadata
- **WHEN** the worker writes a `KnowledgeSegment` to Elasticsearch
- **THEN** it SHALL use `knowledge_segment.metadata` as the vector document metadata
- **AND** that metadata SHALL include `docId`
- **AND** that metadata SHALL include `chunkId`
- **AND** that metadata SHALL include `fileName`
- **AND** that metadata SHALL include `url`
- **AND** that metadata SHALL include `accessibleBy`
- **AND** that metadata SHALL include `parentChunkId`
- **AND** that metadata SHALL include `langchain`
- **AND** that metadata SHALL include `images`

#### Scenario: Vector-store IDs are persisted
- **WHEN** Elasticsearch vector storage returns document IDs for a processed batch
- **THEN** the system SHALL write each returned ID to the corresponding `knowledge_segment.embedding_id`
- **AND** the returned ID order SHALL correspond to the input segment order
- **AND** the system MUST NOT require `embedding_id` to equal `chunk_id`

#### Scenario: Vector-store ID count mismatch fails processing
- **WHEN** Elasticsearch vector storage returns a number of document IDs that is different from the processed segment count
- **THEN** the system SHALL fail the vector-storage attempt
- **AND** the database transaction SHALL roll back
- **AND** Elasticsearch cleanup compensation SHALL run
- **AND** the worker SHALL NOT commit the Kafka message

### Requirement: Vector storage segment scanning
The system SHALL scan embeddable segments in fixed first-page batches until none remain.

#### Scenario: Segment scan filters only pending embeddable segments
- **WHEN** the worker selects a segment batch for a document
- **THEN** it SHALL select rows where `document_id` equals the document id
- **AND** `status` equals `STORED`
- **AND** `skip_embedding` is `false`
- **AND** `embedding_id` is `NULL`

#### Scenario: Segment scan uses fixed first page
- **WHEN** the worker selects a segment batch for a document
- **THEN** it SHALL order by `chunk_order` ascending and `id` ascending
- **AND** it SHALL limit the result to `100` rows
- **AND** it SHALL NOT use offset pagination to advance through the remaining set

#### Scenario: Skipped segments are not embedded
- **WHEN** a segment has `skip_embedding` equal to `true`
- **THEN** the worker SHALL NOT send that segment text to the embedding model
- **AND** the worker SHALL NOT write an Elasticsearch vector document for that segment
- **AND** the segment status SHALL remain `STORED`

#### Scenario: No embeddable segments completes without model calls
- **WHEN** a `CHUNKED` document has no rows where `status` equals `STORED`, `skip_embedding` is `false`, and `embedding_id` is `NULL`
- **THEN** the worker SHALL NOT call the embedding model
- **AND** the worker SHALL NOT write new Elasticsearch vectors
- **AND** the worker SHALL advance the document status to `VECTOR_STORED`

### Requirement: Vector storage transaction and completion
The system SHALL preserve all database changes for one document vector-storage attempt in a single transaction.

#### Scenario: Successful vector storage commits database state together
- **WHEN** all embeddable segments for a `CHUNKED` document are written to Elasticsearch
- **AND** every returned vector-store ID has been assigned to its corresponding segment
- **AND** the final pending-segment double-check returns zero
- **THEN** the system SHALL commit segment `embedding_id` updates
- **AND** it SHALL commit segment status updates to `VECTOR_STORED`
- **AND** it SHALL commit the document status update to `VECTOR_STORED`
- **AND** those database changes SHALL commit in one transaction

#### Scenario: Failed vector storage rolls back database state
- **WHEN** embedding generation, Elasticsearch storage, segment update, double-check, or document status update fails
- **THEN** the database transaction SHALL roll back
- **AND** the document status SHALL remain `CHUNKED`
- **AND** pending embeddable segments SHALL remain eligible for retry

#### Scenario: Double-check gates document completion
- **WHEN** the worker finishes its segment processing loop
- **THEN** it SHALL count remaining rows where `document_id` equals the document id, `status` equals `STORED`, `skip_embedding` is `false`, and `embedding_id` is `NULL`
- **AND** it SHALL update the document status to `VECTOR_STORED` only when that count is zero
- **AND** it SHALL fail the vector-storage attempt when that count is greater than zero

### Requirement: Elasticsearch cleanup compensation
The system SHALL compensate Elasticsearch writes before and after failed vector-storage attempts.

#### Scenario: Worker cleans residual vectors before processing
- **WHEN** the worker starts processing a `CHUNKED` document
- **THEN** it SHALL delete existing Elasticsearch vector documents whose metadata `docId` equals the document id before writing new vectors

#### Scenario: Failure cleans vectors by returned IDs
- **WHEN** a vector-storage attempt fails after Elasticsearch returns one or more vector document IDs
- **THEN** the worker SHALL attempt to delete those returned vector documents from Elasticsearch

#### Scenario: Failure falls back to docId cleanup
- **WHEN** a vector-storage attempt fails
- **THEN** the worker SHALL attempt to delete Elasticsearch vector documents whose metadata `docId` equals the document id
- **AND** cleanup failure SHALL be logged without committing the Kafka message

### Requirement: Vector storage scope boundaries
The system SHALL keep vector storage separate from retrieval, dead-letter queues, scheduled compensation jobs, and document versioning.

#### Scenario: Vector storage does not implement retrieval
- **WHEN** this change is implemented
- **THEN** the system SHALL NOT add a vector search endpoint
- **AND** it SHALL NOT change chat retrieval behavior

#### Scenario: Manual trigger is not the normal application path
- **WHEN** this change is implemented
- **THEN** the normal application path SHALL publish vector-storage events from successful chunking
- **AND** the manual trigger SHALL remain available for end-to-end testing and explicit retry

#### Scenario: Scheduled compensation remains out of scope
- **WHEN** this change is implemented
- **THEN** the system SHALL NOT add a scheduled job that scans and redispatches `CHUNKED` documents
- **AND** it SHALL NOT add a dead-letter queue for vector-storage messages

#### Scenario: Document versions remain out of scope
- **WHEN** vector storage is implemented
- **THEN** the system SHALL NOT add document version activation, deactivation, or version cleanup behavior
