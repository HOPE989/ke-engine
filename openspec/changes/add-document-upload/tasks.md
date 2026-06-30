## Implementation Notes

- Run backend commands from `backend/`.
- Follow RED/GREEN order inside each slice: write the failing test first, confirm it fails for the intended reason, implement the smallest behavior, then rerun the named tests.
- Use `uv run pytest ... -q` for focused tests and `uv run pytest -q` for the backend suite.
- Do not add authentication, chunking, embedding, vector storage, retry APIs, background jobs, or distributed locks in this change.

## 1. Configuration, Dependencies, and Migration Foundation

- [x] 1.1 RED: add `backend/tests/test_document_config.py` covering `DATABASE_URL`, `MAX_UPLOAD_SIZE_MB`, `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`, `MINIO_PUBLIC_BASE_URL`, `MINIO_SECURE`, `MINERU_BASE_URL`, and `MINERU_TIMEOUT_SECONDS` settings loaded from `backend/.env.example`-style names.
- [x] 1.2 RED: run `cd backend; uv run pytest tests/test_document_config.py -q` and confirm it fails because document upload settings and `.env.example` entries are absent.
- [x] 1.3 GREEN: update `backend/pyproject.toml`, `backend/app/core/config.py`, and create `backend/.env.example` with Alembic, MinIO SDK, Magika, multipart upload support, MinerU HTTP client settings, and the documented environment variables.
- [x] 1.4 GREEN: rerun `cd backend; uv run pytest tests/test_document_config.py -q` and confirm the configuration tests pass.
- [x] 1.5 RED: add `backend/tests/test_document_migration.py` that inspects Alembic metadata for `knowledge_document` columns, nullable/default rules, allowed statuses, and indexes on `status`, `upload_user`, and `created_at`.
- [x] 1.6 RED: run `cd backend; uv run pytest tests/test_document_migration.py -q` and confirm it fails because Alembic and the migration do not exist.
- [x] 1.7 GREEN: add `backend/alembic.ini`, `backend/alembic/env.py`, and an initial migration under `backend/alembic/versions/` for the exact `knowledge_document` schema.
- [x] 1.8 GREEN: rerun `cd backend; uv run pytest tests/test_document_migration.py -q` and `cd backend; uv run alembic upgrade head` against the configured development database.

## 2. KnowledgeDocument Lifecycle Slice

- [x] 2.1 RED: add `backend/tests/test_document_model_repository.py` covering `KnowledgeDocument.create(...)` producing an `INIT` row, generated `doc_id` after commit/refresh, `mark_uploaded`, `start_converting`, `mark_converted`, and `rollback_to_uploaded`.
- [x] 2.2 RED: add guarded transition tests in the same file proving `UPLOADED -> CONVERTING` succeeds only when persisted status is still `UPLOADED`, and zero-row updates raise a state conflict error.
- [x] 2.3 RED: run `cd backend; uv run pytest tests/test_document_model_repository.py -q` and confirm it fails because the document module, model, and repository are absent.
- [x] 2.4 GREEN: create `backend/app/modules/document/` with `models.py`, `constants.py`, `repository.py`, and `exceptions.py`; import the model into `backend/app/db/base.py`; implement the domain methods and expected-state repository updates.
- [x] 2.5 GREEN: rerun `cd backend; uv run pytest tests/test_document_model_repository.py -q` and confirm lifecycle persistence and conflict tests pass.

## 3. Upload Validation and Error Envelope Slice

- [ ] 3.1 RED: add `backend/tests/test_document_upload_api_validation.py` for `POST /api/v1/document/upload` missing `file`, `upload_user`, or `accessible_by` returning HTTP 422 with `APIResponse.code=422`, `message=request validation failed`, and `data=null`.
- [ ] 3.2 RED: extend the same test file for blank `upload_user`, blank `accessible_by`, empty file, missing/blank filename, unreadable stream, and oversized file returning the specified 400 or 413 envelope before any `knowledge_document` insert.
- [ ] 3.3 RED: add a path-like filename case proving `doc_title` and object-key suffixes use a safe basename and raw path segments are not used as object-key prefixes.
- [ ] 3.4 RED: run `cd backend; uv run pytest tests/test_document_upload_api_validation.py -q` and confirm it fails because the route and validation layer are absent.
- [ ] 3.5 GREEN: add `backend/app/modules/document/router.py`, `schemas.py`, `service.py`, and error mapping helpers; mount the router from `backend/app/api/v1/router.py`; normalize FastAPI validation errors and semantic validation errors into the shared `APIResponse` contract.
- [ ] 3.6 GREEN: rerun `cd backend; uv run pytest tests/test_document_upload_api_validation.py -q` and confirm validation tests pass without MinIO or MinerU calls.

## 4. Magika Detection and Processor Factory Slice

- [ ] 4.1 RED: add `backend/tests/test_document_file_type.py` covering Magika PDF detection, Markdown detection, `.md` / `.markdown` / `.txt` generic text fallback, unsupported file type, and Magika runtime failure.
- [ ] 4.2 RED: add processor factory tests proving PDF maps to `PdfDocumentProcessor`, plain text maps to `PlainTextDocumentProcessor`, and missing processors return the 415 `unsupported file type` envelope.
- [ ] 4.3 RED: run `cd backend; uv run pytest tests/test_document_file_type.py -q` and confirm it fails because detector and processors are absent.
- [ ] 4.4 GREEN: add `file_types.py` and `processors.py` with `MagikaFileTypeDetector`, business file type mapping, `DocumentProcessorFactory`, `PlainTextDocumentProcessor`, and `PdfDocumentProcessor` stubs wired only as far as tests require.
- [ ] 4.5 GREEN: rerun `cd backend; uv run pytest tests/test_document_file_type.py -q` and confirm all detection and factory tests pass.

## 5. Original Storage and Plain Text Upload Slice

- [ ] 5.1 RED: add `backend/tests/test_document_storage.py` covering bucket creation, MinIO object keys under `documents/{doc_id}/original/{safe_filename}`, URL construction from `MINIO_PUBLIC_BASE_URL`, and threadpool execution for synchronous SDK calls.
- [ ] 5.2 RED: run `cd backend; uv run pytest tests/test_document_storage.py -q` and confirm it fails because the storage adapter is absent.
- [ ] 5.3 GREEN: add `backend/app/modules/document/storage.py` with a thin `DocumentStorage` wrapper around the official `minio` SDK and deterministic URL/key helpers.
- [ ] 5.4 GREEN: rerun `cd backend; uv run pytest tests/test_document_storage.py -q` and confirm storage adapter tests pass with a fake or mocked MinIO client.
- [ ] 5.5 RED: add `backend/tests/test_document_plain_text_upload.py` covering a `.md` upload that persists `INIT`, uploads the original, sets `doc_url`, sets `converted_doc_url=doc_url`, transitions to `CONVERTED`, and returns HTTP 200 document metadata.
- [ ] 5.6 RED: extend the same file for MinIO original upload failure returning HTTP 502 `document storage failed`, keeping status `INIT`, and not calling any processor.
- [ ] 5.7 RED: run `cd backend; uv run pytest tests/test_document_plain_text_upload.py -q` and confirm it fails because the service does not yet orchestrate storage and plain text conversion.
- [ ] 5.8 GREEN: implement the `DocumentUploadService` plain text flow: validate, detect type, commit `INIT`, upload original, transition to `UPLOADED`, invoke the plain text processor, set `converted_doc_url`, and transition to `CONVERTED` without holding a DB transaction across MinIO calls.
- [ ] 5.9 GREEN: rerun `cd backend; uv run pytest tests/test_document_plain_text_upload.py -q` and confirm the plain text success and storage failure tests pass.

## 6. PDF Conversion Success Slice

- [ ] 6.1 RED: add `backend/tests/test_document_pdf_conversion.py` covering MinerU `POST /file_parse`, safe ZIP extraction, image upload under `documents/{doc_id}/assets/`, final Markdown upload under `documents/{doc_id}/converted/document.md`, relative image link rewriting to full MinIO URLs, and first-version alt text `图片描述`.
- [ ] 6.2 RED: add multiple-Markdown selection tests in the same file: basename match wins, matching parent directory wins second, and lexicographically first normalized Markdown path wins last.
- [ ] 6.3 RED: add an API-level PDF success test proving the endpoint persists `INIT`, uploads the original, transitions `UPLOADED -> CONVERTING -> CONVERTED`, sets `converted_doc_url` to the final Markdown URL, and returns HTTP 200.
- [ ] 6.4 RED: run `cd backend; uv run pytest tests/test_document_pdf_conversion.py -q` and confirm it fails because MinerU conversion and PDF processing are absent.
- [ ] 6.5 GREEN: add `backend/app/modules/document/mineru.py` and `markdown.py`; complete `PdfDocumentProcessor` for the successful path using local temporary ZIP processing before converted object uploads.
- [ ] 6.6 GREEN: rerun `cd backend; uv run pytest tests/test_document_pdf_conversion.py -q` and confirm PDF success tests pass.

## 7. PDF Failure and Rollback Slice

- [ ] 7.1 RED: add `backend/tests/test_document_pdf_failures.py` covering MinerU request failure, corrupted ZIP, unsafe ZIP path traversal, duplicate normalized ZIP paths, no usable Markdown, Markdown rewrite failure, converted asset upload failure, converted Markdown upload failure, and expected-state conflict.
- [ ] 7.2 RED: assert each conversion failure after original upload returns HTTP 502 `document conversion failed`, leaves the original `doc_url`, restores or keeps status `UPLOADED`, and does not set `converted_doc_url`.
- [ ] 7.3 RED: add rollback failure coverage proving conversion failure after `CONVERTING` returns HTTP 500 `document state rollback failed` when restoring `UPLOADED` fails.
- [ ] 7.4 RED: run `cd backend; uv run pytest tests/test_document_pdf_failures.py -q` and confirm it fails for the missing failure handling.
- [ ] 7.5 GREEN: implement PDF failure normalization, expected-state conflict mapping to HTTP 409 `document state conflict`, and rollback failure mapping to HTTP 500 `document state rollback failed`.
- [ ] 7.6 GREEN: rerun `cd backend; uv run pytest tests/test_document_pdf_failures.py -q` and confirm all failure matrix tests pass.

## 8. Final Contract Verification

- [ ] 8.1 Run focused document tests: `cd backend; uv run pytest tests/test_document_config.py tests/test_document_migration.py tests/test_document_model_repository.py tests/test_document_upload_api_validation.py tests/test_document_file_type.py tests/test_document_storage.py tests/test_document_plain_text_upload.py tests/test_document_pdf_conversion.py tests/test_document_pdf_failures.py -q`.
- [ ] 8.2 Run the full backend suite: `cd backend; uv run pytest -q`.
- [ ] 8.3 Run migration verification from a clean development database: `cd backend; uv run alembic downgrade base && uv run alembic upgrade head`.
- [ ] 8.4 Run OpenSpec validation: `openspec validate add-document-upload --strict`.
- [ ] 8.5 Confirm `openspec status --change add-document-upload` shows artifacts complete and implementation tasks tracked.
