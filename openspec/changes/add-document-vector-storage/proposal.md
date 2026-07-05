## Why

RAG ingestion currently stops after converted Markdown is split into database-backed knowledge segments. The system needs a controlled embed-and-store stage that turns `CHUNKED` documents into Elasticsearch-backed vector documents while keeping database lifecycle state consistent.

## What Changes

- Add a manual document vector-storage trigger endpoint that validates a document and dispatches a Kafka event.
- Dispatch the same vector-storage event after successful document chunking as the normal application path.
- Add a Kafka embed-and-store worker that consumes document vector-storage events.
- Generate embeddings with `OpenAIEmbeddings` using `text-embedding-v4`, hard-coded `chunk_size = 9`, and configurable `embedding_dimensions = 1536`.
- Write vector documents to Elasticsearch using `segment.text` as page content and `segment.metadata` as metadata.
- Store the Elasticsearch-generated vector document ID in `knowledge_segment.embedding_id`.
- Advance embeddable segments from `STORED` to `VECTOR_STORED`.
- Advance documents from `CHUNKED` to `VECTOR_STORED` only after all non-skipped segments are vector stored.
- Use a single document-level Redis lock, a long database transaction for the document's DB updates, fixed first-page scanning, final double-checking, and Elasticsearch cleanup compensation.
- Keep retrieval APIs, question answering, document versioning, dead-letter queues, and scheduled compensation jobs out of scope.

## Capabilities

### New Capabilities
- `document-vector-storage`: Manual and Kafka-backed embedding/vector storage for chunked documents.

### Modified Capabilities
- `document-upload`: Extend the document lifecycle with `VECTOR_STORED`.
- `document-chunking`: Persist newly chunked segments with `STORED` status instead of `INIT`.

## Impact

- Backend API: adds a document vector-storage trigger endpoint under the document module.
- Backend workers: adds an embed-and-store Kafka consumer alongside the existing conversion consumer.
- Database: extends document status constraints and changes segment initial status semantics.
- Dependencies: adds Elasticsearch vector-store integration via `langchain-elasticsearch`.
- Configuration: adds Elasticsearch URL/index and embedding dimension settings.
- Infrastructure: uses the existing Kafka, Redis, PostgreSQL, and Elasticsearch services.
- Tests: adds coverage for dispatch, worker lifecycle, status transitions, fixed-page scanning, vector-store ID persistence, transaction rollback, Elasticsearch cleanup compensation, and Kafka commit behavior.
