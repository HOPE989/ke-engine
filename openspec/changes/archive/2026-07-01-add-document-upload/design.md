## Context

The backend is a FastAPI application with versioned routers, shared response
envelopes, SQLAlchemy async database primitives, and several placeholder/demo
modules. The placeholder `auth`, `users`, and `orders` modules and the current
chat demo are not architectural templates for new production features.

This change adds the first RAG ingestion entry point: accept a file, store the
original object in MinIO, persist document metadata in Postgres, and synchronously
produce a converted Markdown URL for supported inputs.

Authentication remains out of scope. The upload API accepts `upload_user` and
`accessible_by` as request fields until a later auth-focused change replaces
them with real identity and permission resolution.

## Goals / Non-Goals

**Goals:**

- Add `POST /api/v1/document/upload` for synchronous upload-to-`CONVERTED`
  ingestion.
- Persist `knowledge_document` with an `INIT` row before external side effects.
- Store original files, converted Markdown, and extracted PDF images in MinIO.
- Convert PDFs synchronously through MinerU.
- Detect supported files with Magika.
- Support only PDF and plain text inputs (`.md`, `.markdown`, `.txt`) in the
  first version.
- Normalize validation, persistence, storage, conversion, and state-conflict
  failures into stable `APIResponse` envelopes.
- Protect lifecycle transitions with expected-state database updates.
- Keep database transactions short and never hold one open across MinIO or
  MinerU calls.
- Implement the feature in FastAPI/Python style: router functions, dependency
  functions, module-level workflow functions, and explicit resource ownership.

**Non-Goals:**

- No authentication or authorization enforcement.
- No chunking, embedding, vector database writes, search, or `knowledge_segment`.
- No background queue, retry API, scheduled cleanup, or distributed lock.
- No Office/HTML/image ingestion beyond images extracted from MinerU output.
- No service-class or factory-class hierarchy copied from Java/Spring patterns.

## Architecture Principles

### 1. FastAPI is the composition boundary

Routers own HTTP concerns: multipart inputs, FastAPI validation, dependency
declarations, response envelopes, and exception mapping. They should delegate
domain work to ordinary module functions.

Do not introduce a `DocumentUploadService` class solely to hold dependencies.
Spring-style `Service` classes are not useful here because FastAPI does not
provide Spring's container scope, transaction proxying, AOP, or lifecycle
semantics.

Acceptable classes are limited to cases with real value:

- SQLAlchemy mapped models.
- Pydantic request/response schemas.
- Small value objects where a dataclass materially clarifies data shape.
- External resource adapters or clients that own protocol/lifecycle details.

### 2. Request-scoped work stays request-scoped

`get_db()` creates a request-scoped `AsyncSession`. That session, any temporary
validated upload object, and any database unit of work must not be shared across
requests.

Repository behavior should be implemented as focused functions that accept the
session explicitly, for example:

```python
async def create_init_document(session: AsyncSession, ...) -> KnowledgeDocument:
    ...

async def mark_uploaded(session: AsyncSession, doc_id: int, doc_url: str) -> None:
    ...
```

A repository class is not part of the first-version boundary unless a later
requirement creates real state or lifecycle that a function cannot express
cleanly.

### 3. Project-level resources have explicit owners

DB engine/session factory ownership remains in `app.db.session`; request code
consumes only `get_db()`.

External project resources should live outside `app.modules.document` when they
are not document-specific:

- MinIO SDK client belongs to infrastructure.
- MinerU HTTP client belongs to infrastructure or an integration module.
- Magika runtime belongs to infrastructure or a focused file-type integration.

Resources that need cleanup, such as `httpx.AsyncClient`, should be initialized
and closed through FastAPI lifespan/app-state style accessors. Resources without
cleanup requirements may use a small explicit project-level getter, but the
getter should live in the resource owner module, not in the document workflow.

Document-specific storage semantics, such as object keys and public URL
construction, may stay under `app.modules.document.storage` because they encode
document domain paths.

### 4. Document module layout

The first implementation should prefer this shape:

```text
backend/app/modules/document/
  router.py       # FastAPI endpoint, validation boundary, error mapping
  schemas.py      # Pydantic request/response models and validated input shapes
  workflow.py     # upload_document(...) orchestration function
  models.py       # KnowledgeDocument SQLAlchemy model
  repository.py   # database functions, not a repository class by default
  storage.py      # document object-key and URL helpers, plus storage adapter if useful
  file_types.py   # detect_document_file_type(...)
  mineru.py       # document-facing MinerU conversion helper if needed
  markdown.py     # ZIP Markdown selection and image link rewriting helpers
  errors.py       # stable document-domain exceptions
```

Avoid adding `service.py` for a stateless orchestration class. Avoid adding a
`DocumentProcessorFactory` for two initial branches; a `match` or small dispatch
function is clearer until the format matrix grows.

### 5. Upload workflow

The core use case should be an ordinary async function. Its dependencies are
explicit parameters, not hidden globals:

```python
async def upload_document(
    *,
    session: AsyncSession,
    upload: ValidatedDocumentUpload,
    resources: DocumentUploadResources,
) -> DocumentMetadata:
    ...
```

`DocumentUploadResources` may be a small value object or typed mapping assembled
at the FastAPI boundary. It should not construct heavy resources itself; it only
groups resources already owned by infrastructure accessors.

Workflow order:

1. Detect file type before persistence.
2. Create and commit an `INIT` document row.
3. Upload the original file to MinIO outside a DB transaction.
4. Mark the document `UPLOADED`.
5. For plain text, set `converted_doc_url = doc_url` and mark `CONVERTED`.
6. For PDF, transition `UPLOADED -> CONVERTING`, call MinerU, upload converted
   assets/Markdown, then mark `CONVERTED`.
7. On PDF conversion failure, keep or restore `UPLOADED` and never set
   `converted_doc_url`.

### 6. Lifecycle state protection

State transitions use expected-state database updates:

```sql
UPDATE knowledge_document
SET status = 'CONVERTING'
WHERE doc_id = :doc_id
  AND status = 'UPLOADED'
```

Zero affected rows means a state conflict. This is sufficient for the first
synchronous upload flow because each request creates a new document row and
there is no retry endpoint or background worker competing for the same `doc_id`.

### 7. File type detection

Magika is the primary detector. Extension checks are only a narrow fallback for
generic text that should be accepted as `.md`, `.markdown`, or `.txt`.

Mapping:

- PDF: Magika identifies PDF or reports `application/pdf`.
- Markdown/plain text: Magika identifies Markdown or text and the extension is
  one of the supported text extensions.
- Unsupported: reject with HTTP 415 before persistence.
- Magika runtime failure: reject with HTTP 500 before persistence.

### 8. MinIO storage

Use the official MinIO Python SDK; do not hand-roll S3 protocol behavior. The
SDK is synchronous, so calls from async endpoints must run off the event loop.

Object keys:

```text
documents/{doc_id}/original/{safe_filename}
documents/{doc_id}/converted/document.md
documents/{doc_id}/assets/{image_filename}
```

URLs stored in the database are stable full public URLs built from
`MINIO_PUBLIC_BASE_URL`, bucket, and object key. Do not store expiring presigned
URLs in this first version.

### 9. PDF conversion

PDF conversion calls MinerU `POST /file_parse` with zip output and image return
enabled. The ZIP is validated and extracted into a temporary local directory
before any converted objects are uploaded.

Markdown selection order:

1. Prefer Markdown whose normalized basename matches the uploaded PDF stem.
2. Prefer Markdown under a directory whose normalized name matches the PDF stem.
3. Otherwise choose the lexicographically first normalized Markdown path.

Unsafe ZIP paths, duplicate normalized paths, corrupt ZIPs, no usable Markdown,
Markdown rewrite failures, MinerU request failures, and converted upload
failures are conversion failures.

Relative Markdown image links are rewritten to MinIO URLs. First-version image
alt text is `图片描述`.

### 10. Error responses

All upload errors use the shared `APIResponse` envelope. `code` equals the HTTP
status code, `data` is `null`, and `message` is stable.

| Failure | HTTP | Message |
| --- | --- | --- |
| Missing multipart field | 422 | `request validation failed` |
| Empty file, blank user/scope, missing filename, unreadable stream | 400 | `invalid upload request` |
| File exceeds `MAX_UPLOAD_SIZE_MB` | 413 | `file too large` |
| Unsupported file type | 415 | `unsupported file type` |
| Initial document persistence failure | 500 | `document persistence failed` |
| Magika runtime failure | 500 | `file type detection failed` |
| MinIO original upload failure | 502 | `document storage failed` |
| Expected-state transition conflict | 409 | `document state conflict` |
| MinerU request failure, invalid ZIP, unsafe ZIP, no usable Markdown, or converted upload failure | 502 | `document conversion failed` |
| Rollback from `CONVERTING` to `UPLOADED` fails | 500 | `document state rollback failed` |

Responses must not include secret values, MinIO credentials, local file paths,
stack traces, raw provider exceptions, or full MinerU response bodies.

### 11. Database schema

The first migration creates `knowledge_document`:

- `doc_id`: `BIGINT` identity primary key.
- `doc_title`: `VARCHAR(1024) NOT NULL`.
- `upload_user`: `VARCHAR(255) NOT NULL`.
- `doc_url`: `VARCHAR(2048) NULL`.
- `converted_doc_url`: `VARCHAR(2048) NULL`.
- `status`: `VARCHAR(32) NOT NULL DEFAULT 'INIT'`, constrained to `INIT`,
  `UPLOADED`, `CONVERTING`, and `CONVERTED`.
- `accessible_by`: `VARCHAR(1024) NOT NULL`.
- `created_at`: timezone-aware timestamp with current-time server default.
- `updated_at`: timezone-aware timestamp with current-time server default and
  application-side updates on change.

Indexes: primary key on `doc_id`, plus indexes on `status`, `upload_user`, and
`created_at`.

### 12. Testing strategy

Tests should assert behavior and contracts rather than the existence of service
or factory classes. Good tests exercise:

- HTTP envelopes and status codes.
- DB state transitions and expected-state conflicts.
- Object keys and URLs.
- Event-loop safety for synchronous MinIO calls.
- MinerU ZIP validation and Markdown rewriting.
- Absence of persistence before validation/type-detection failures.

Do not add tests that require or bless `DocumentUploadService`,
`DocumentProcessorFactory`, or similar Java-style scaffolding.

## Risks / Trade-offs

- Synchronous PDF conversion can make upload requests slow; background jobs are
  intentionally deferred until a later change.
- MinIO upload and DB updates are not atomic; persist `INIT` before side effects
  and keep failed states observable.
- Some converted uploads can partially succeed before a later converted upload
  fails; the DB must not publish `converted_doc_url` or `CONVERTED` until every
  required converted upload succeeds.
- Magika can classify text generically; extension fallback is intentionally
  narrow to avoid accepting unsupported formats accidentally.
- Full public URLs require MinIO bucket/object access to be configured outside
  the application.

## Settled First-Version Boundaries

- Placeholder modules and the chat demo are not implementation patterns for this
  change.
- Stateless orchestration is implemented as functions, not service classes.
- Processor factory is not part of the first-version boundary.
- Request-scoped DB session and workflow state are never project-level singletons.
- Project-level external resources are owned by infrastructure accessors or
  FastAPI app state, not by the upload workflow.
