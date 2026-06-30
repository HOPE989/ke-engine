## Context

The backend is a FastAPI application with versioned routers, SQLAlchemy async database primitives, and placeholder `auth`, `users`, and `orders` modules. The existing chat demo intentionally skipped authentication, persistence, retrieval, and document ingestion. The next RAG step is document upload: accept a file, store it in MinIO, persist metadata in Postgres, and convert supported inputs to a Markdown URL that later chunking and embedding can consume.

Authentication is a placeholder for this change. The upload API accepts `upload_user` and `accessible_by` as request fields. Real user identity and role resolution can replace those inputs in a later auth-focused change.

## Goals / Non-Goals

**Goals:**

- Add a dedicated `document` module for the upload-to-`CONVERTED` ingestion stage.
- Persist `knowledge_document` with a real `INIT` state before external side effects.
- Store original files, converted Markdown, and PDF images in MinIO through the official Python SDK.
- Convert PDF files synchronously with MinerU.
- Use Magika for file type detection instead of hand-maintained magic byte checks.
- Validate upload inputs, file size, and stable error response contracts before external side effects.
- Support only PDF and plain text inputs (`.md`, `.markdown`, `.txt`) in the first version.
- Protect state transitions with database expected-state updates instead of distributed locks.
- Add Alembic and a first migration for `knowledge_document`.
- Add `backend/.env.example` using the environment variable names the application reads.

**Non-Goals:**

- No authentication or authorization enforcement.
- No chunking, embedding, vector database writes, search, or `knowledge_segment`.
- No background queue, retry API, or scheduled cleanup.
- No Office/HTML/image ingestion beyond images extracted from MinerU output.
- No Apache Tika service, `python-magic` system dependency, or custom file signature registry.
- No Redis or distributed lock for the first synchronous upload flow.

## Decisions

### 1. Use a dedicated `document` module

The upload workflow will live under `backend/app/modules/document/` with router, schemas, model, repository, service, storage, converter, file type, processor, and Markdown helper responsibilities. This follows the existing module layout and keeps ingestion separate from chat and placeholder auth/users/orders behavior.

Alternative considered: put ingestion under `chat` or a generic RAG module. That would couple upload with later retrieval behavior too early.

### 2. Keep `KnowledgeDocument` as a small domain model

`KnowledgeDocument.create(...)` creates an `INIT` document before MinIO or MinerU work begins. Domain methods own state changes such as `mark_uploaded`, `start_converting`, `mark_converted`, and `rollback_to_uploaded`. The service orchestrates workflow and persistence, but does not scatter raw status string updates.

The service should commit the `INIT` row before external side effects so the generated `doc_id` can be used in object keys and failures remain observable. If the initial insert fails, the request fails before uploading anything.

State changes should be guarded by the expected current state. For example, `UPLOADED -> CONVERTING` should only succeed when the current row still has status `UPLOADED`. If an update affects no rows, the service treats it as a state conflict and stops the workflow.

### 3. Use database state guards instead of distributed locks

The first version does not need a distributed lock because each upload request creates and processes its own new `knowledge_document` row. There is no retry endpoint, background worker, or multi-consumer queue that can intentionally process the same `doc_id` concurrently.

The concurrency boundary is the document lifecycle row. Use short database transactions and conditional updates such as:

```sql
UPDATE knowledge_document
SET status = 'CONVERTING'
WHERE doc_id = :doc_id
  AND status = 'UPLOADED'
```

This is preferable to holding a Redis lock across MinIO and MinerU calls. PDF conversion can be slow, and a long-lived lock would require TTL sizing, renewal, token-safe release, and recovery behavior. Those concerns should wait until the system adds retry APIs, background tasks, or multiple workers competing for the same document.

The service must not keep a database transaction open while calling MinIO or MinerU. It should commit state changes before and after external side effects, and use expected-state checks for each transition.

### 4. Use explicit file processors behind a factory

The service calls one `process_file` method that asks `DocumentProcessorFactory` for a handler. Initial handlers are:

- `PdfDocumentProcessor` for PDF files.
- `PlainTextDocumentProcessor` for `.md`, `.markdown`, and `.txt`.

Future formats can add new processor implementations without changing the upload service flow.

### 5. Validate upload inputs before persistence

The API must reject malformed upload requests before creating `knowledge_document` or calling MinIO/MinerU. Required checks:

- `file` exists and has at least one byte.
- `file.filename` is present after stripping whitespace.
- `upload_user` and `accessible_by` are present and non-blank after trimming.
- uploaded content does not exceed `MAX_UPLOAD_SIZE_MB`, default `100`.
- raw file names are normalized to a safe basename for display and object-key suffixes; path segments from user input are not trusted.

Missing multipart fields remain FastAPI validation failures with HTTP 422. Semantic validation failures use HTTP 400, except file size which uses HTTP 413 and unsupported type which uses HTTP 415.

### 6. Use Magika for file type detection

File type detection will be implemented behind a `FileTypeDetector` abstraction with a first concrete `MagikaFileTypeDetector`. The detector uses Magika's Python API to classify uploaded content and then maps Magika output into the small business file type set used by the processor factory.

Initial mapping:

- PDF: Magika identifies PDF or reports `application/pdf`.
- Markdown: Magika identifies Markdown, or the extension is `.md` / `.markdown` and Magika identifies text.
- Plain text: Magika identifies generic text, or the extension is `.txt` and Magika identifies text.
- Unsupported: any other result fails with HTTP 415 before creating an `INIT` row.
- The detector uses Magika's final output result and maps it to the supported business document types.
- Magika runtime errors fail with HTTP 500 and message `file type detection failed`.

Magika is preferred over Tika because it has a Python package and does not require a Java service. It is preferred over `python-magic` because it avoids a system `libmagic` dependency, which is especially useful on Windows and in containers. Extension checks remain only as a narrow helper for Markdown/text formats, where content alone may be generic text.

### 7. Use MinIO's official Python SDK behind a storage adapter

The system will not implement S3/MinIO protocol behavior directly. A thin `DocumentStorage` adapter will wrap the synchronous `minio` SDK with methods such as `ensure_bucket`, `upload_file`, `upload_bytes`, and `build_public_url`.

Because the MinIO SDK is synchronous and the endpoint is async, blocking storage calls should run through a threadpool such as `anyio.to_thread.run_sync`.

Object keys use the persisted `doc_id` and safe generated paths:

```text
documents/{doc_id}/original/{safe_filename}
documents/{doc_id}/converted/document.md
documents/{doc_id}/assets/{image_filename}
```

Database URLs store stable full URLs built from `MINIO_PUBLIC_BASE_URL`, bucket, and object key. The design does not store expiring presigned URLs.

### 8. Convert PDFs synchronously with MinerU

The upload API should only return success for a PDF after MinerU conversion and Markdown/image upload are complete. The converter calls MinerU `POST /file_parse` with `response_format_zip=true` and `return_images=true`.

The processor safely extracts the returned ZIP to a temporary directory, selects Markdown according to MinerU output conventions, uploads images and the final Markdown to MinIO, rewrites relative image links to MinIO URLs, and fills image alt text with the initial mock description `图片描述`.

Markdown selection does not treat multiple Markdown files as an automatic error. The selection order is:

1. Prefer a Markdown file whose normalized basename matches the uploaded PDF stem.
2. Prefer a Markdown file under a directory whose normalized name matches the uploaded PDF stem.
3. Otherwise choose the lexicographically first normalized Markdown path from the ZIP.

No usable Markdown file, a corrupted ZIP, an unsafe ZIP entry, or a duplicate normalized ZIP path is a conversion failure.

The processor performs ZIP validation and Markdown rewriting in the local temporary directory before uploading converted objects. It uploads converted assets and Markdown only after local processing succeeds. The document is not marked `CONVERTED` and `converted_doc_url` is not saved until every required converted object upload succeeds. If an upload fails after some converted objects were written, those objects are unreferenced because the database still points only at the original `doc_url`; the first version does not require synchronous object cleanup.

If conversion fails after original upload, the document remains or rolls back to `UPLOADED`, and the endpoint returns a normalized error.

### 9. Define stable error responses

All document upload errors use the shared `APIResponse` error envelope. `code` equals the HTTP status code, `data` is `null`, and `message` is a stable short phrase. Responses must not include secret values, MinIO credentials, file system paths, stack traces, raw provider exceptions, or full MinerU response bodies.

| Failure | HTTP | Message |
| --- | --- | --- |
| Missing multipart field | 422 | `request validation failed` |
| Empty file, blank user/scope, missing filename, unreadable file stream | 400 | `invalid upload request` |
| File exceeds `MAX_UPLOAD_SIZE_MB` | 413 | `file too large` |
| Unsupported file type | 415 | `unsupported file type` |
| Initial document persistence failure | 500 | `document persistence failed` |
| Magika runtime failure | 500 | `file type detection failed` |
| MinIO original upload failure | 502 | `document storage failed` |
| Expected-state transition conflict | 409 | `document state conflict` |
| MinerU request failure, invalid ZIP, no usable Markdown, unsafe ZIP entry, converted upload failure | 502 | `document conversion failed` |
| Rollback from `CONVERTING` to `UPLOADED` fails after conversion failure | 500 | `document state rollback failed` |

### 10. Define the `knowledge_document` schema

The first migration creates `knowledge_document` with:

- `doc_id`: `BIGINT` identity primary key.
- `doc_title`: `VARCHAR(1024) NOT NULL`.
- `upload_user`: `VARCHAR(255) NOT NULL`.
- `doc_url`: `VARCHAR(2048) NULL`.
- `converted_doc_url`: `VARCHAR(2048) NULL`.
- `status`: `VARCHAR(32) NOT NULL DEFAULT 'INIT'` with allowed values `INIT`, `UPLOADED`, `CONVERTING`, and `CONVERTED`.
- `accessible_by`: `VARCHAR(1024) NOT NULL`, stored as the request's role/scope string for this version.
- `created_at`: timezone-aware timestamp with server default current time.
- `updated_at`: timezone-aware timestamp with server default current time and application-side updates on changes.

Indexes: primary key on `doc_id`, plus indexes on `status`, `upload_user`, and `created_at`.

### 11. Add Alembic and environment variables

Alembic becomes the database migration mechanism. `env.py` should reuse `app.db.base.Base.metadata` and import project models so autogeneration can see them.

`backend/.env.example` should include:

```env
DATABASE_URL=postgresql+asyncpg://ke_engine:ke_engine@localhost:5432/ke_engine
MAX_UPLOAD_SIZE_MB=100
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=ke-engine-documents
MINIO_PUBLIC_BASE_URL=http://localhost:9000
MINIO_SECURE=false
MINERU_BASE_URL=http://localhost:8000
MINERU_TIMEOUT_SECONDS=120
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=gpt-4o-mini
```

Settings should read these exact names.

## Risks / Trade-offs

- Synchronous PDF conversion can make upload requests slow -> keep the first version simple and add background jobs only after the sync path is proven.
- MinIO upload and database updates are not one atomic transaction -> persist `INIT` before side effects and keep failed states visible for manual inspection.
- Competing state updates could otherwise double-process a document -> guard each lifecycle transition with an expected current status and treat zero-row updates as conflicts.
- Distributed locking may become necessary later for retries or background workers -> defer Redis lock design until there is a real shared `doc_id` processing path.
- Full public MinIO URLs require bucket/object read access to be configured appropriately -> document this in `.env.example` expectations and storage tests.
- ZIP extraction can be abused by path traversal entries -> extraction logic must validate resolved paths stay inside the temporary directory.
- Markdown image rewriting can miss unusual syntax -> cover normal Markdown image syntax first and leave complex Markdown parsing for later if needed.
- Magika may classify some text formats generically -> use extensions only as a narrow secondary signal for Markdown and text while keeping unsupported formats rejected until explicit processors are added.
- Converted object uploads can partially succeed -> do not publish `converted_doc_url` or mark `CONVERTED` until every required converted object upload succeeds.

## Migration Plan

1. Add Alembic configuration and a first migration for `knowledge_document`.
2. Add document models and import them from Alembic metadata discovery.
3. Apply migrations in local/dev environments before calling the upload endpoint.
4. Rollback removes the upload endpoint code and downgrades the migration if no downstream tables depend on `knowledge_document`.

## Settled First-Version Boundaries

- Multiple Markdown files in MinerU output are resolved by deterministic selection rules instead of treated as an error by default.
- Converted object uploads are not published through `converted_doc_url` until every required converted object upload succeeds.
- Processor factory and `KnowledgeDocument` domain methods remain part of the first implementation boundary.
- Environment examples use the exact variable names listed above.
