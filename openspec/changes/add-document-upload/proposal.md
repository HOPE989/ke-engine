## Why

RAG ingestion needs a first persistent entry point that accepts user documents, stores original files, and prepares converted Markdown for later chunking and embedding. The existing backend has chat and placeholder modules only, so document ingestion needs its own module, storage integration, and database migration boundary before later RAG steps can build on it.

## What Changes

- Add a new `document` backend module for document upload and conversion through `POST /api/v1/document/upload`.
- Add a persisted `knowledge_document` table and domain model with explicit lifecycle states from `INIT` through `CONVERTED`.
- Store original and converted files in MinIO using the official Python SDK through a thin storage adapter.
- Convert PDF files synchronously with MinerU and save the converted Markdown plus extracted images to MinIO.
- Detect supported file types with Magika and map them to the document processor factory.
- Support `.md`, `.markdown`, and `.txt` as plain text inputs that complete conversion by pointing `converted_doc_url` to the original file URL.
- Reject unsupported file types with HTTP 415.
- Normalize upload, storage, conversion, persistence, and state-conflict failures through stable `APIResponse` error contracts.
- Add Alembic as the database migration mechanism for `knowledge_document`.
- Add `backend/.env.example` with environment variables for database, upload limits, MinIO, MinerU, and existing OpenAI-compatible settings.
- Protect document lifecycle updates with database expected-state checks instead of a distributed lock in the first version.
- Keep authentication and authorization out of scope; `upload_user` and `accessible_by` remain request parameters for this change.
- Do not add chunking, embedding, vector storage, document search, retry APIs, background job processing, or distributed locking in this change.

## Capabilities

### New Capabilities

- `document-upload`: Synchronous document upload and conversion to `CONVERTED` state for the first RAG ingestion stage.

### Modified Capabilities

- None.

## Impact

- Backend API: new document upload endpoint under `/api/v1/document`.
- Backend modules: new `backend/app/modules/document/` package.
- Database: Alembic setup plus a migration for `knowledge_document`.
- Dependencies: add Alembic, MinIO Python SDK, Magika, and an HTTP client suitable for MinerU calls if not already available.
- Configuration: add `DATABASE_URL`, `MAX_UPLOAD_SIZE_MB`, `MINIO_*`, `MINERU_*`, and existing `OPENAI_*` examples in `backend/.env.example`.
- External systems: requires Postgres, MinIO, and MinerU for full PDF upload conversion behavior.
