## 1. Schema, Dependencies, and Settings

- [ ] 1.1 RED: Add focused tests for `langchain-elasticsearch` dependency availability, `elasticsearch_url`, `elasticsearch_index`, `embedding_dimensions`, `EMBEDDING_DIMENSIONS`, `VECTOR_STORED`, and segment default `STORED`.
- [ ] 1.2 GREEN: Add the dependency, settings fields, config defaults, ORM status updates, and Alembic migration for document/segment status changes.
- [ ] 1.3 VERIFY: Run the focused config, migration, and persistence tests that fail in 1.1.

## 2. Typed Event and Dispatch Triggers

- [ ] 2.1 RED: Add tests for `DocumentEmbedStoreRequested` serialization, dispatcher topic/key/flush behavior, chunk-success dispatch after persistence, manual API dispatch success, and manual API Kafka dispatch failure returning `vector storage dispatch failed`.
- [ ] 2.2 GREEN: Implement the vector-storage event type, dispatcher, runtime wiring, chunking success dispatch, and manual `POST /api/v1/document/{doc_id}/embed-store` endpoint.
- [ ] 2.3 VERIFY: Run focused event, dispatcher, chunking workflow, and API tests from 2.1.

## 3. Vector Store Adapter

- [ ] 3.1 RED: Add adapter tests for `OpenAIEmbeddings(model="text-embedding-v4", chunk_size=9, dimensions=settings.embedding_dimensions, check_embedding_ctx_length=False)`.
- [ ] 3.2 RED: Add adapter tests proving `segment.text` becomes page content, `segment.metadata` becomes metadata, returned Elasticsearch IDs are preserved in order, returned-ID count mismatch fails, and cleanup can delete by IDs and by metadata `docId`.
- [ ] 3.3 GREEN: Implement the minimal Elasticsearch vector-store adapter and minimal index ensure/validate for configured dimensions.
- [ ] 3.4 VERIFY: Run focused vector-store adapter tests from 3.1 and 3.2.

## 4. Repository Operations

- [ ] 4.1 RED: Add repository tests for selecting the first 100 pending embeddable segments ordered by `chunk_order` then `id`, without offset pagination.
- [ ] 4.2 RED: Add repository tests for batch `embedding_id` updates, `VECTOR_STORED` segment status updates, remaining-pending double-check count, and document `CHUNKED -> VECTOR_STORED` completion inside an existing transaction.
- [ ] 4.3 GREEN: Implement repository methods required by the vector-storage workflow.
- [ ] 4.4 VERIFY: Run focused repository tests from 4.1 and 4.2.

## 5. Vector Storage Workflow

- [ ] 5.1 RED: Add workflow tests for success with multiple DB pages, zero embeddable segments, skipped parent segments, fixed first-page scanning, final double-check, and document completion.
- [ ] 5.2 RED: Add workflow tests for Redis lock busy, OpenAI failure, Elasticsearch failure, returned-ID count mismatch, DB update failure, double-check failure, DB rollback, pre-run ES cleanup by `docId`, and failure cleanup by returned IDs plus `docId`.
- [ ] 5.3 GREEN: Implement the vector-storage workflow with Redis lock, pre-run cleanup, one long DB transaction, model/vector-store calls inside the transaction, batch scanning, double-check, rollback, and cleanup compensation.
- [ ] 5.4 VERIFY: Run focused vector-storage workflow tests from 5.1 and 5.2.

## 6. Kafka Worker Commit Semantics

- [ ] 6.1 RED: Add worker tests for topic subscription, consumer group id, commit after successful completion, commit for missing document, commit for already `VECTOR_STORED`, and commit for non-`CHUNKED` business state.
- [ ] 6.2 RED: Add worker tests for no commit on busy lock, OpenAI/ES/DB infrastructure failure, vector ID count mismatch, and double-check failure.
- [ ] 6.3 GREEN: Implement the vector-storage Kafka consumer loop and message handler with explicit terminal-vs-retryable commit rules.
- [ ] 6.4 VERIFY: Run focused Kafka worker tests from 6.1 and 6.2.

## 7. Full Verification

- [ ] 7.1 Run `cd backend && uv run python -m pytest`.
- [ ] 7.2 Run `openspec validate add-document-vector-storage --strict`.
