## 1. Schema and Dependencies

- [x] 1.1 RED: Add a dependency/import test proving `langchain_text_splitters.MarkdownHeaderTextSplitter` and `RecursiveCharacterTextSplitter` are available.
- [x] 1.2 GREEN: Add `langchain-text-splitters` to backend dependencies and refresh the lockfile.
- [x] 1.3 VERIFY: Run the focused dependency/import test and confirm it fails before 1.2 and passes after 1.2.
- [x] 1.4 RED: Add migration/model tests proving `knowledge_document` keeps existing columns, including Snowflake-generated `doc_id` and existing `file_type`, while accepting `CHUNKED`.
- [x] 1.5 GREEN: Update the Alembic migration and ORM model status constraints for `CHUNKED` without changing existing `knowledge_document` columns.
- [x] 1.6 RED: Add migration/model tests for `knowledge_segment`, including Snowflake `id`, Snowflake string `chunk_id`, `TEXT` content, `JSONB` metadata, `skip_embedding`, `status DEFAULT 'INIT'`, foreign key, and indexes.
- [x] 1.7 GREEN: Implement the `knowledge_segment` Alembic migration and ORM model.
- [x] 1.8 VERIFY: Run focused migration/model tests for document status and segment schema.

## 2. Request and Response Contract

- [x] 2.1 RED: Add API/schema tests for missing fields, non-integers, `chunk_size <= 0`, `overlap < 0`, and `overlap >= chunk_size`.
- [x] 2.2 GREEN: Add request and response schemas for `POST /api/v1/document/{doc_id}/chunk` with `chunk_size > 0`, `overlap >= 0`, and `overlap < chunk_size`.
- [x] 2.3 VERIFY: Run the focused request/response schema tests.

## 3. Converted Markdown Loading

- [x] 3.1 RED: Add tests for resolving a valid `converted_doc_url` into an object key using the configured MinIO `public_base_url` and `bucket`.
- [x] 3.2 RED: Add tests for invalid converted URLs: wrong base URL, wrong bucket, and a path that cannot produce a non-empty object key.
- [x] 3.3 RED: Add tests for Markdown loading failures: object missing, storage download error, and non-UTF-8 bytes.
- [x] 3.4 GREEN: Implement a converted Markdown loader that parses `converted_doc_url`, validates base URL and bucket, downloads through `DocumentObjectStorage.download_bytes(object_key=...)`, and decodes bytes as UTF-8.
- [x] 3.5 VERIFY: Run focused converted Markdown loader tests and confirm stable errors map to `document state conflict`, `converted markdown unavailable`, and `converted markdown invalid`.

## 4. LangChain Splitter Wrapper

- [x] 4.1 RED: Add splitter tests proving `MarkdownHeaderTextSplitter` uses `#` through `######`, `Header 1` through `Header 6`, `strip_headers=True`, and `return_each_line=False`.
- [x] 4.2 RED: Add splitter tests proving `RecursiveCharacterTextSplitter` uses request `chunk_size`, request `overlap`, `length_function=len`, `is_separator_regex=False`, and the configured CJK-friendly separator list.
- [x] 4.3 RED: Add behavior tests for normal section output, oversized parent plus child output, child inheritance of parent LangChain metadata, empty chunk discard, and zero-segment output.
- [x] 4.4 GREEN: Implement the LangChain-backed splitter wrapper without hand-writing Markdown parsing or recursive chunking algorithms.
- [x] 4.5 VERIFY: Run focused splitter tests.

## 5. Segment Drafts and Metadata

- [x] 5.1 RED: Add tests proving segment drafts allocate Snowflake `id` and Snowflake string `chunk_id` values.
- [x] 5.2 RED: Add tests proving `chunk_order` starts at `0`, follows document reading order, and includes parent rows.
- [x] 5.3 RED: Add tests proving metadata contains `skipEmbedding`, `chunkId`, `docId`, `fileName`, `url`, `accessibleBy`, `parentChunkId`, and `langchain`.
- [x] 5.4 RED: Add tests proving `chunkId`, `docId`, and `skipEmbedding` intentionally duplicate database fields into metadata.
- [x] 5.5 GREEN: Implement segment draft construction and metadata construction with camelCase top-level keys and namespaced LangChain metadata.
- [x] 5.6 VERIFY: Run focused segment draft and metadata tests.

## 6. Repository Transactions

- [x] 6.1 RED: Add repository tests for expected-state completion from `CONVERTED` to `CHUNKED`.
- [x] 6.2 RED: Add repository tests proving bulk segment insert and `CONVERTED` to `CHUNKED` completion commit in one database transaction.
- [x] 6.3 RED: Add repository tests proving persistence failure rolls back partial segment inserts and returns `chunk persistence failed`.
- [x] 6.4 RED: Add repository tests proving pre-persistence failures leave the document at `CONVERTED` without a rollback transition.
- [x] 6.5 GREEN: Implement repository completion with segments and `CONVERTED` to `CHUNKED` in one transaction.
- [x] 6.6 VERIFY: Run focused repository transaction tests.

## 7. Redis Chunk Lock

- [x] 7.1 RED: Add lock helper tests for acquiring and releasing `document:{doc_id}:chunk`.
- [x] 7.2 RED: Add lock helper tests for busy lock returning `document state conflict`.
- [x] 7.3 RED: Add lock helper tests for Redis/lock infrastructure failure returning `chunk lock unavailable`.
- [x] 7.4 GREEN: Implement the document chunking lock helper using existing Redis lock infrastructure.
- [x] 7.5 VERIFY: Run focused lock helper tests.

## 8. Chunking Workflow

- [x] 8.1 RED: Add workflow tests for missing document, non-`CONVERTED` document, already `CHUNKED` document, missing `converted_doc_url`, invalid converted URL, and busy lock.
- [x] 8.2 GREEN: Implement workflow precondition checks and stable 404/409 responses.
- [x] 8.3 VERIFY: Run focused workflow precondition tests.
- [x] 8.4 RED: Add workflow tests for successful chunking and zero-segment success.
- [x] 8.5 GREEN: Implement the happy path: acquire lock, load Markdown, run splitter in a threadpool, build segment drafts, persist segments, mark `CHUNKED`, and release lock.
- [x] 8.6 VERIFY: Run focused workflow success tests.
- [x] 8.7 RED: Add workflow tests for Redis unavailable, Markdown download failure, non-UTF-8 Markdown, splitter failure, and persistence failure.
- [x] 8.8 GREEN: Implement stable workflow error mapping while leaving failed chunking attempts at `CONVERTED`.
- [x] 8.9 VERIFY: Run focused workflow failure tests.

## 9. API Endpoint

- [x] 9.1 RED: Add API tests for HTTP status codes and `APIResponse` envelopes for success, validation errors, not found, state conflict, lock unavailable, converted Markdown unavailable, converted Markdown invalid, splitting failure, and persistence failure.
- [x] 9.2 GREEN: Implement `POST /api/v1/document/{doc_id}/chunk` in the document router.
- [x] 9.3 VERIFY: Run focused API endpoint tests.

## 10. Regression and OpenSpec Verification

- [x] 10.1 Run existing document upload, conversion, storage, and status query tests to catch lifecycle regressions.
- [x] 10.2 Run the backend test suite or the documented document-module subset before marking implementation complete.
- [x] 10.3 Validate the OpenSpec change with `openspec validate "add-document-chunking" --type change --strict`.

## 11. Chunk Lifecycle Semantics Revision

- [x] 11.1 RED: Update specs and tests so chunking no longer persists `CHUNKING`; completion atomically inserts segments and updates `CONVERTED` to `CHUNKED`.
- [x] 11.2 GREEN: Remove `start_chunking` and chunk rollback workflow usage; make repository completion update `CONVERTED` to `CHUNKED` in one transaction.
- [x] 11.3 VERIFY: Run focused workflow, repository, API, migration/model tests, and strict OpenSpec validation.
