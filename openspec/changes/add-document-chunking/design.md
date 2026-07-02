## Context

The document ingestion flow currently accepts PDF, Markdown, and plain text uploads and asynchronously advances documents to `CONVERTED`. At `CONVERTED`, every supported document has a `converted_doc_url` that points to Markdown content. RAG ingestion cannot proceed to embedding or Elasticsearch until the converted Markdown is split into durable segment records.

Authentication is still a placeholder in this project. The existing upload API accepts `upload_user` and `accessible_by` as request fields, so chunking inherits document ownership and access metadata from `knowledge_document` instead of introducing new identity or authorization behavior.

The current document module already owns document lifecycle models, object storage access, repository patterns, Redis lock helpers, and Snowflake ID generation. Chunking should stay inside that module boundary and reuse those patterns.

## Goals / Non-Goals

**Goals:**

- Add a manual chunking endpoint for a user-selected converted document.
- Let callers choose `chunk_size` and `overlap` for the first and only chunk set for the current document record.
- Persist `knowledge_segment` rows with stable Snowflake `chunk_id` values.
- Resolve and validate `converted_doc_url` before reading the converted Markdown from MinIO.
- Support parent-child chunks when a Markdown header section exceeds `chunk_size`.
- Store metadata that is self-contained for later Elasticsearch ingestion.
- Protect one document from concurrent chunking with a Redis distributed lock.
- Persist generated segments and complete the document status transition atomically in one database transaction.

**Non-Goals:**

- No automatic background chunking after conversion.
- No Kafka topic or polling API for chunking.
- No embedding, vector storage, Elasticsearch writes, or outbox flow.
- No chunk versioning or document versioning in this change.
- No re-chunking of an already `CHUNKED` document.
- No authentication or authorization redesign.
- No true distributed transaction across database, object storage, and Elasticsearch.

## Decisions

### 1. Use a synchronous HTTP response, not a background job

The endpoint will complete chunking before returning:

```text
POST /api/v1/document/{doc_id}/chunk
  -> validate parameters
  -> acquire document chunk lock
  -> resolve converted_doc_url to an object key
  -> download and decode converted Markdown
  -> split Markdown
  -> persist segments and mark document CHUNKED
  -> return segment_count
```

The route can remain `async def` so existing async repository and storage boundaries stay natural. The CPU or blocking splitter work should run in a threadpool, while database and MinIO calls stay awaitable.

Alternative considered: Kafka-backed chunking with a polling API. That would fit long-running work but adds a second status API and operational complexity. Chunking is a user-initiated text-processing step and the caller needs `segment_count`, so synchronous semantics are simpler for the first version.

### 2. Use `CONVERTED -> CHUNKING -> CHUNKED`

`CHUNKING` is a short-lived lifecycle state used while the request owns the chunking operation. The endpoint accepts only `CONVERTED` documents. `CHUNKED` documents reject another chunk request with `409 document state conflict`.

If chunking produces zero valid segments, the operation still succeeds and marks the document `CHUNKED` with `segment_count = 0`. A content-empty converted document is not a system failure.

### 3. Use Redis distributed lock plus database expected-state checks

The endpoint should acquire a Redis lock with a key shaped like:

```text
document:{doc_id}:chunk
```

The lock prevents multiple API instances from chunking the same document at the same time. Database expected-state updates still guard correctness:

```text
CONVERTED -> CHUNKING
CHUNKING -> CHUNKED
```

Both protections are useful. The lock avoids wasted duplicate splitting work; expected-state updates protect lifecycle correctness if a request races, retries, or loses the lock unexpectedly.

### 4. Use one database transaction for segment persistence and completion

The durable completion phase should run in one database transaction:

```text
insert all knowledge_segment rows
update knowledge_document.status = CHUNKED
commit
```

This is a normal database transaction, equivalent to a Java service method using `@Transactional`. It is not an XA/JTA/Seata distributed transaction. This change only writes to the database; MinIO is read-only in this flow and Elasticsearch is out of scope.

### 5. Resolve `converted_doc_url` to a MinIO object key

The existing storage adapter downloads by object key, while `knowledge_document.converted_doc_url` stores a public URL. Chunking should parse the URL instead of guessing the key from `doc_id`.

The accepted URL shape is:

```text
{public_base_url}/{bucket}/{object_key}
```

For converted Markdown, the object key is expected to resolve to the existing converted Markdown object, normally:

```text
documents/{doc_id}/converted/document.md
```

The implementation should:

- require `converted_doc_url` to use the configured MinIO public base URL and bucket;
- extract the object key from the URL path after the bucket segment;
- reject URLs that do not belong to the configured base URL or bucket;
- download bytes through `DocumentObjectStorage.download_bytes(object_key=...)`;
- decode bytes as UTF-8 with strict error handling;
- avoid falling back to a derived `doc_id` key when the stored URL is invalid.

This makes bad persisted document state visible instead of silently reading a different object.

### 6. Split Markdown with LangChain splitters

The project should add `langchain-text-splitters` and use:

```python
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
```

Chunking uses a two-step split:

1. `MarkdownHeaderTextSplitter` splits by Markdown headers and carries header metadata.
2. `RecursiveCharacterTextSplitter` splits only those header sections whose text exceeds `chunk_size`.

The splitter configuration is part of the contract:

```python
headers_to_split_on = [
    ("#", "Header 1"),
    ("##", "Header 2"),
    ("###", "Header 3"),
    ("####", "Header 4"),
    ("#####", "Header 5"),
    ("######", "Header 6"),
]

MarkdownHeaderTextSplitter(
    headers_to_split_on=headers_to_split_on,
    return_each_line=False,
    strip_headers=False,
)

RecursiveCharacterTextSplitter(
    chunk_size=chunk_size,
    chunk_overlap=overlap,
    length_function=len,
    is_separator_regex=False,
    separators=[
        "\n\n",
        "\n",
        " ",
        ".",
        ",",
        "\u200b",
        "\uff0c",
        "\u3001",
        "\uff0e",
        "\u3002",
        "",
    ],
)
```

`strip_headers=False` is required so a parent segment can store the complete header section text, including the header line. Recursive child chunks inherit the parent header metadata under `metadata.langchain`.

The first version treats converted plain text as Markdown without headers. MinerU output is also treated as Markdown, even when all headings are effectively top-level.

The implementation should prefer established Python packages for domain behavior whenever a mature package exists. For this change, Markdown header splitting and recursive character splitting are delegated to LangChain splitters instead of hand-written parsing or chunking algorithms. Custom code should focus on orchestration, parameter validation, metadata shaping, parent-child segment construction, locking, and persistence.

### 7. Preserve parent sections and skip their embedding

If a header section does not exceed `chunk_size`, it becomes a normal segment:

```text
skip_embedding = false
metadata.parentChunkId = null
```

If a header section exceeds `chunk_size`, the system persists:

- one parent segment containing the complete header section text, with `skip_embedding = true`
- multiple child segments containing recursive splits, each with `skip_embedding = false`
- `metadata.parentChunkId` on each child pointing to the parent `chunkId`

Parent segments keep full context for later reconstruction while avoiding noisy embedding records.

All segments created by this change have `status = INIT` and `embedding_id = null`. Later embedding/vector storage work can extend the status lifecycle in a separate change.

### 8. Use zero-based `chunk_order` across all persisted rows

`chunk_order` starts at `0` and includes every persisted row, including parent rows:

```text
0 normal segment A
1 parent segment B, skip_embedding=true
2 child segment B-1
3 child segment B-2
4 normal segment C
```

This preserves document reading order in a single sortable column.

### 9. Store self-contained segment metadata for Elasticsearch

Each segment stores metadata as JSONB. It intentionally duplicates selected database fields because later Elasticsearch payloads should be self-contained.

Metadata keys use camelCase:

```json
{
  "skipEmbedding": false,
  "chunkId": "10001",
  "docId": "90001",
  "fileName": "guide.pdf",
  "url": "http://minio/.../document.md",
  "accessibleBy": "team-a",
  "parentChunkId": null,
  "langchain": {
    "Header 1": "第一章"
  }
}
```

`langchain` stores the splitter-provided metadata without flattening it into the top-level payload. This avoids collisions with system-owned metadata keys.

### 10. Use stable error responses for processing failures

The API should keep processing failures testable by returning stable HTTP status codes and messages:

| Failure | HTTP status | `APIResponse.message` |
| --- | --- | --- |
| Redis lock infrastructure unavailable | `503` | `chunk lock unavailable` |
| `converted_doc_url` does not match configured MinIO base URL or bucket | `409` | `document state conflict` |
| `converted_doc_url` path cannot be parsed into an object key | `409` | `document state conflict` |
| Converted Markdown object is missing or cannot be downloaded | `502` | `converted markdown unavailable` |
| Converted Markdown bytes are not valid UTF-8 | `422` | `converted markdown invalid` |
| LangChain splitting raises an unexpected error | `500` | `chunk splitting failed` |
| Segment insertion or `CHUNKED` status update fails | `500` | `chunk persistence failed` |
| Best-effort rollback from `CHUNKING` to `CONVERTED` fails | `500` | `chunk rollback failed` |

## Risks / Trade-offs

- Long request duration for very large Markdown files -> The first version accepts synchronous behavior; if real usage hits gateway timeouts, a later change can move chunking behind Kafka and add status polling.
- `CHUNKING` document left behind after process death -> No automatic repair in this change. Manual database repair or a later stale-state retry mechanism can address it.
- Redis lock lost while a request is still running -> Database expected-state checks still protect lifecycle correctness.
- JSONB ties the schema to PostgreSQL behavior -> The project already uses async PostgreSQL through `asyncpg`; JSONB is appropriate for queryable metadata.
- Metadata duplication can drift from columns if updated later -> Segment rows are immutable for this first version after chunking, so drift risk is low.
