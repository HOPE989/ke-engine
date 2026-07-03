## ADDED Requirements

### Requirement: Document chunking endpoint
The system SHALL expose a synchronous document chunking endpoint at `POST /api/v1/document/{doc_id}/chunk`.

#### Scenario: Chunk request accepts required parameters
- **WHEN** a client sends JSON with integer `chunk_size` and integer `overlap`
- **THEN** the system SHALL validate the request as a document chunking request

#### Scenario: Successful chunking response
- **WHEN** a converted document is chunked successfully
- **THEN** the system SHALL return HTTP 200
- **AND** the response body SHALL use the shared `APIResponse` success envelope
- **AND** the response data SHALL include `doc_id` serialized as a string
- **AND** the response data SHALL include `status` equal to `CHUNKED`
- **AND** the response data SHALL include `segment_count` equal to the number of persisted segments

#### Scenario: Missing or malformed chunk parameters are rejected
- **WHEN** a client omits `chunk_size` or `overlap`
- **OR** a client sends either field as a non-integer value
- **THEN** the system SHALL return HTTP 422 with `APIResponse.code` equal to `422`
- **AND** the response message SHALL be `request validation failed`

#### Scenario: Invalid chunk parameter relationship is rejected
- **WHEN** `chunk_size` is less than or equal to `0`
- **OR** `overlap` is less than `0`
- **OR** `overlap` is greater than or equal to `chunk_size`
- **THEN** the system SHALL return HTTP 400 with `APIResponse.code` equal to `400`
- **AND** the response message SHALL be `invalid chunk request`

### Requirement: Document chunking preconditions
The system SHALL only chunk existing documents that have completed conversion and have not already been chunked.

#### Scenario: Missing document is rejected
- **WHEN** a client requests chunking for a `doc_id` that does not exist
- **THEN** the system SHALL return HTTP 404 with `APIResponse.code` equal to `404`
- **AND** the response message SHALL be `document not found`

#### Scenario: Non-converted document is rejected
- **WHEN** a client requests chunking for a document whose status is not `CONVERTED`
- **THEN** the system SHALL return HTTP 409 with `APIResponse.code` equal to `409`
- **AND** the response message SHALL be `document state conflict`
- **AND** the system MUST NOT create `knowledge_segment` records

#### Scenario: Already chunked document returns existing result
- **WHEN** a client requests chunking for a document whose status is `CHUNKED`
- **THEN** the system SHALL return HTTP 200
- **AND** the response body SHALL use the shared `APIResponse` success envelope
- **AND** the response data SHALL include `status` equal to `CHUNKED`
- **AND** the response data SHALL include `segment_count` equal to the number of persisted segments where `skip_embedding` is false
- **AND** the system MUST NOT delete, replace, or append `knowledge_segment` records for that document

#### Scenario: Converted document without converted URL is rejected
- **WHEN** a client requests chunking for a `CONVERTED` document that has no `converted_doc_url`
- **THEN** the system SHALL return HTTP 409 with `APIResponse.code` equal to `409`
- **AND** the response message SHALL be `document state conflict`
- **AND** the system MUST NOT create `knowledge_segment` records

### Requirement: Converted Markdown retrieval
The system SHALL resolve `knowledge_document.converted_doc_url` to a validated MinIO object key before downloading Markdown content.

#### Scenario: Converted URL is resolved to object key
- **WHEN** a client requests chunking for a `CONVERTED` document with `converted_doc_url`
- **THEN** the system SHALL parse `converted_doc_url` using the configured storage `public_base_url` and `bucket`
- **AND** the system SHALL extract the object key from the URL path after the bucket segment
- **AND** the system SHALL download bytes through `DocumentObjectStorage.download_bytes(object_key=...)`
- **AND** the system SHALL decode the downloaded bytes as UTF-8

#### Scenario: Converted URL outside configured storage is rejected
- **WHEN** `converted_doc_url` does not belong to the configured storage `public_base_url` or `bucket`
- **THEN** the system SHALL return HTTP 409 with `APIResponse.code` equal to `409`
- **AND** the response message SHALL be `document state conflict`
- **AND** the system MUST NOT create `knowledge_segment` records

#### Scenario: Converted URL path cannot produce object key
- **WHEN** `converted_doc_url` belongs to the configured storage base but its path cannot be parsed into a non-empty object key after the bucket segment
- **THEN** the system SHALL return HTTP 409 with `APIResponse.code` equal to `409`
- **AND** the response message SHALL be `document state conflict`
- **AND** the system MUST NOT create `knowledge_segment` records

#### Scenario: Converted Markdown download fails
- **WHEN** the converted Markdown object does not exist
- **OR** object storage returns a download error
- **THEN** the system SHALL return HTTP 502 with `APIResponse.code` equal to `502`
- **AND** the response message SHALL be `converted markdown unavailable`
- **AND** the system MUST NOT create `knowledge_segment` records

#### Scenario: Converted Markdown is not UTF-8
- **WHEN** the converted Markdown bytes cannot be decoded as UTF-8
- **THEN** the system SHALL return HTTP 422 with `APIResponse.code` equal to `422`
- **AND** the response message SHALL be `converted markdown invalid`
- **AND** the system MUST NOT create `knowledge_segment` records

### Requirement: Chunking concurrency control
The system SHALL protect document chunking with a per-document Redis distributed lock and a final document lifecycle expected-state update.

#### Scenario: Chunk lock is acquired before chunking
- **WHEN** the system starts chunking a document
- **THEN** it SHALL acquire a Redis distributed lock for `document:{doc_id}:chunk`
- **AND** it SHALL release the lock after the chunking attempt finishes

#### Scenario: Busy chunk lock is rejected
- **WHEN** another request already holds the chunk lock for the same `doc_id`
- **THEN** the system SHALL return HTTP 409 with `APIResponse.code` equal to `409`
- **AND** the response message SHALL be `document state conflict`
- **AND** the system MUST NOT create `knowledge_segment` records

#### Scenario: Chunk lock infrastructure is unavailable
- **WHEN** the system cannot reach Redis or cannot evaluate the chunk lock
- **THEN** the system SHALL return HTTP 503 with `APIResponse.code` equal to `503`
- **AND** the response message SHALL be `chunk lock unavailable`
- **AND** the system MUST NOT create `knowledge_segment` records

#### Scenario: Chunking keeps intermediate state in request scope
- **WHEN** the system has acquired the chunk lock for a `CONVERTED` document
- **THEN** the system SHALL NOT persist a `CHUNKING` document status before downloading or splitting Markdown
- **AND** the document SHALL remain `CONVERTED` until the final persistence transaction commits

### Requirement: Markdown chunk splitting
The system SHALL split converted Markdown by Markdown headers first and by recursive character length second.

#### Scenario: LangChain splitters are used
- **WHEN** the system chunks a converted document
- **THEN** it SHALL use `MarkdownHeaderTextSplitter` from `langchain-text-splitters` for first-pass Markdown header splitting
- **AND** it SHALL use `RecursiveCharacterTextSplitter` from `langchain-text-splitters` for length-based child splitting

#### Scenario: Markdown header splitter configuration is stable
- **WHEN** the system constructs the `MarkdownHeaderTextSplitter`
- **THEN** it SHALL set `headers_to_split_on` for `#`, `##`, `###`, `####`, `#####`, and `######`
- **AND** it SHALL map those headers to `Header 1`, `Header 2`, `Header 3`, `Header 4`, `Header 5`, and `Header 6`
- **AND** it SHALL set `strip_headers` to `True`
- **AND** it SHALL set `return_each_line` to `False`

#### Scenario: Recursive splitter configuration is stable
- **WHEN** the system constructs the `RecursiveCharacterTextSplitter`
- **THEN** it SHALL set `chunk_size` from the request `chunk_size`
- **AND** it SHALL set `chunk_overlap` from the request `overlap`
- **AND** it SHALL set `length_function` to Python `len`
- **AND** it SHALL set `is_separator_regex` to `False`
- **AND** it SHALL include separators for paragraph breaks, line breaks, spaces, ASCII punctuation, zero-width space, fullwidth comma, ideographic comma, fullwidth full stop, ideographic full stop, and empty-string fallback

#### Scenario: Header section within chunk size creates a normal segment
- **WHEN** a first-pass header section has non-empty text
- **AND** the section text length is less than or equal to `chunk_size`
- **THEN** the system SHALL persist one segment for that section
- **AND** the segment SHALL have `skip_embedding` set to `false`
- **AND** the segment metadata SHALL have `parentChunkId` set to `null`

#### Scenario: Header section exceeding chunk size creates parent and child segments
- **WHEN** a first-pass header section has text length greater than `chunk_size`
- **THEN** the system SHALL persist one parent segment containing the complete header section body text without Markdown header lines
- **AND** the parent segment SHALL have `skip_embedding` set to `true`
- **AND** the system SHALL recursively split that parent text into child segments
- **AND** each child segment SHALL have `skip_embedding` set to `false`
- **AND** each child segment metadata SHALL have `parentChunkId` equal to the parent segment `chunkId`
- **AND** each child segment SHALL inherit the parent section LangChain header metadata under `metadata.langchain`

#### Scenario: Splitter failure returns stable error
- **WHEN** LangChain splitting raises an unexpected error
- **THEN** the system SHALL return HTTP 500 with `APIResponse.code` equal to `500`
- **AND** the response message SHALL be `chunk splitting failed`
- **AND** the system MUST NOT create `knowledge_segment` records

#### Scenario: Empty chunks are discarded
- **WHEN** splitter output produces an empty or whitespace-only text fragment
- **THEN** the system SHALL NOT persist a segment for that fragment

#### Scenario: Zero segment result succeeds
- **WHEN** chunking completes and no valid non-empty segments are produced
- **THEN** the system SHALL mark the document as `CHUNKED`
- **AND** the response `segment_count` SHALL be `0`

### Requirement: Knowledge segment schema
The system SHALL persist document chunks in `knowledge_segment` with stable identifiers, ordering, status, embedding flags, and JSONB metadata.

#### Scenario: Knowledge segment table exists after migration
- **WHEN** Alembic migrations are applied
- **THEN** the database SHALL contain a `knowledge_segment` table

#### Scenario: Knowledge segment table columns are defined
- **WHEN** the `knowledge_segment` table is inspected
- **THEN** `id` SHALL be a `BIGINT` primary key generated by Snowflake
- **AND** `chunk_id` SHALL be a `VARCHAR(255) NOT NULL` stable chunk identifier generated by Snowflake
- **AND** `text` SHALL be a PostgreSQL `TEXT NOT NULL` column
- **AND** `document_id` SHALL be a `BIGINT NOT NULL` foreign key to `knowledge_document.doc_id`
- **AND** `chunk_order` SHALL be an `INT NOT NULL`
- **AND** `embedding_id` SHALL be a `VARCHAR(255) NULL`
- **AND** `status` SHALL be a `VARCHAR(255) NOT NULL DEFAULT 'INIT'`
- **AND** `metadata` SHALL be a PostgreSQL `JSONB NOT NULL` column
- **AND** `skip_embedding` SHALL be a `BOOLEAN NOT NULL`

#### Scenario: Knowledge segment status is initialized
- **WHEN** a `knowledge_segment` record is persisted
- **THEN** `status` SHALL be `INIT`

#### Scenario: Knowledge segment indexes are present
- **WHEN** migrations are applied
- **THEN** the table SHALL have indexes supporting lookups by `document_id`, `chunk_id`, `status`, and `chunk_order`

#### Scenario: Chunk order starts at zero
- **WHEN** the system persists segments for one document
- **THEN** `chunk_order` SHALL start at `0`
- **AND** every persisted row for the document, including parent segments, SHALL consume one `chunk_order` value
- **AND** `chunk_order` values SHALL follow document reading order

### Requirement: Segment metadata payload
The system SHALL store self-contained metadata on each segment for later Elasticsearch ingestion.

#### Scenario: Segment metadata includes document and chunk fields
- **WHEN** the system persists a segment
- **THEN** segment `metadata` SHALL include `skipEmbedding`
- **AND** segment `metadata` SHALL include `chunkId`
- **AND** segment `metadata` SHALL include `docId`
- **AND** segment `metadata` SHALL include `fileName`
- **AND** segment `metadata` SHALL include `url`
- **AND** segment `metadata` SHALL include `accessibleBy`
- **AND** segment `metadata` SHALL include `parentChunkId`
- **AND** segment `metadata` SHALL include `langchain`

#### Scenario: Metadata duplicates selected database fields
- **WHEN** the system persists a segment
- **THEN** `metadata.skipEmbedding` SHALL equal the segment `skip_embedding` column
- **AND** `metadata.chunkId` SHALL equal the segment `chunk_id` column
- **AND** `metadata.docId` SHALL equal the segment `document_id` column serialized as a string

#### Scenario: Metadata inherits document fields
- **WHEN** the system persists a segment
- **THEN** `metadata.fileName` SHALL equal the source document `doc_title`
- **AND** `metadata.url` SHALL equal the source document `converted_doc_url`
- **AND** `metadata.accessibleBy` SHALL equal the source document `accessible_by`

#### Scenario: LangChain metadata is namespaced
- **WHEN** the LangChain splitter produces metadata for a segment
- **THEN** the system SHALL store that metadata under `metadata.langchain`
- **AND** the system MUST NOT flatten LangChain metadata into the top-level segment metadata payload

### Requirement: Chunk persistence transaction
The system SHALL atomically persist generated segments and complete the document chunking lifecycle in one database transaction.

#### Scenario: Successful chunking commits segments and document state together
- **WHEN** Markdown splitting completes successfully
- **THEN** the system SHALL insert all generated `knowledge_segment` rows
- **AND** the system SHALL update the document status from `CONVERTED` to `CHUNKED`
- **AND** those inserts and status update SHALL commit in one database transaction

#### Scenario: Persistence failure rolls back segment writes
- **WHEN** segment persistence or the `CONVERTED` to `CHUNKED` status update fails
- **THEN** the database transaction SHALL roll back
- **AND** the system MUST NOT leave a partial set of `knowledge_segment` rows committed for that chunking attempt
- **AND** the system SHALL return HTTP 500 with `APIResponse.code` equal to `500`
- **AND** the response message SHALL be `chunk persistence failed`

#### Scenario: Pre-persistence chunking failure leaves document converted
- **WHEN** Markdown download or splitting fails before segment persistence
- **THEN** the system SHALL leave the persisted document status as `CONVERTED`
- **AND** the system SHALL return the stable error response for the original failure

### Requirement: Chunking scope boundaries
The system SHALL keep chunking separate from embedding, vector storage, and chunk versioning.

#### Scenario: Chunking does not write embeddings
- **WHEN** document chunking succeeds
- **THEN** the system SHALL NOT create embeddings
- **AND** the system SHALL NOT write vectors or text chunks to Elasticsearch
- **AND** every persisted segment SHALL have `embedding_id` set to `null`
- **AND** every persisted segment SHALL have `status` set to `INIT`

#### Scenario: Chunking is one-to-one with the current document record
- **WHEN** a document has already reached `CHUNKED`
- **THEN** the system SHALL NOT allow a second chunk set for the same document record
- **AND** the system SHALL rely on future document versioning to support future chunking versions

#### Scenario: Chunking dependency is available
- **WHEN** backend dependencies are installed
- **THEN** the `langchain-text-splitters` Python package SHALL be available for Markdown and recursive character splitting
