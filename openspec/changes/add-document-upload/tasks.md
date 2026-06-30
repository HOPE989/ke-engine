## Implementation Notes

- Run backend commands from `backend/`.
- Use strict RED/GREEN order for every implementation slice: write the failing
  test first, run it and confirm the expected failure, implement the smallest
  code needed, then rerun the focused test.
- Use `uv run --extra dev pytest ... -q` for tests while `pytest` remains in the
  optional `dev` extra.
- Do not use the placeholder modules or chat demo as architecture templates.
- Prefer FastAPI/Python style: router functions, dependency functions,
  module-level workflow functions, explicit resource ownership, and request
  state passed as parameters.
- Do not add `DocumentUploadService`, `DocumentProcessorFactory`, background
  jobs, retry APIs, chunking, embedding, vector storage, document search,
  authentication, authorization enforcement, or distributed locks in this
  change.
- Do not implement behavior not declared in the specs.

## 0. Baseline Cleanup

- [x] 0.1 RED: add tests proving the chat demo exposes a module-level function
  instead of `ChatService`, and placeholder modules do not carry unused
  service/repository/model/security scaffolding.
- [x] 0.2 RED: run
  `uv run --extra dev pytest tests/test_chat_service.py tests/test_chat_module.py tests/test_project_layout.py -q`
  and confirm the tests fail because `chat()` is absent and placeholder
  scaffolding files still exist.
- [x] 0.3 GREEN: refactor the chat demo to a module-level `chat()` function,
  keep `get_chat_model()` as the explicit project-level cached model accessor,
  and remove unused placeholder module scaffolding.
- [x] 0.4 GREEN: rerun the focused tests and confirm the baseline cleanup tests
  pass.

## 1. Configuration, Dependencies, and Resource Ownership

- [ ] 1.1 RED: add `backend/tests/test_document_config.py` covering
  `DATABASE_URL`, `MAX_UPLOAD_SIZE_MB`, `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`,
  `MINIO_SECRET_KEY`, `MINIO_BUCKET`, `MINIO_PUBLIC_BASE_URL`, `MINIO_SECURE`,
  `MINERU_BASE_URL`, and `MINERU_TIMEOUT_SECONDS` settings loaded from
  `backend/.env.example`-style names.
- [ ] 1.2 RED: run `uv run --extra dev pytest tests/test_document_config.py -q`
  and confirm it fails because document upload settings and env examples are
  absent.
- [ ] 1.3 GREEN: add only the required document upload dependencies and settings:
  Alembic, MinIO SDK, Magika, multipart upload support, and MinerU settings.
- [ ] 1.4 GREEN: rerun `uv run --extra dev pytest tests/test_document_config.py -q`
  and confirm configuration tests pass.
- [ ] 1.5 RED: add `backend/tests/test_document_resource_ownership.py` proving
  project-level MinIO/Magika/MinerU resources are created by infrastructure
  accessors or app-state dependencies, reused across requests, and not
  constructed by the upload workflow.
- [ ] 1.6 RED: run `uv run --extra dev pytest tests/test_document_resource_ownership.py -q`
  and confirm it fails because the document infrastructure accessors are absent.
- [ ] 1.7 GREEN: implement the minimal infrastructure resource ownership needed
  by document upload. Resources with cleanup, such as MinerU `httpx.AsyncClient`,
  must be closed through FastAPI lifespan/app-state or an equivalent explicit
  shutdown hook.
- [ ] 1.8 GREEN: rerun `uv run --extra dev pytest tests/test_document_resource_ownership.py -q`
  and confirm resource ownership tests pass.

## 2. Migration and KnowledgeDocument Persistence

- [ ] 2.1 RED: add `backend/tests/test_document_migration.py` that inspects the
  Alembic migration for the exact `knowledge_document` columns, nullable rules,
  default rules, allowed statuses, and indexes on `status`, `upload_user`, and
  `created_at`.
- [ ] 2.2 RED: run `uv run --extra dev pytest tests/test_document_migration.py -q`
  and confirm it fails because Alembic configuration and the migration are
  absent.
- [ ] 2.3 GREEN: add Alembic configuration and an initial migration for the exact
  `knowledge_document` schema.
- [ ] 2.4 GREEN: rerun `uv run --extra dev pytest tests/test_document_migration.py -q`
  and confirm migration metadata tests pass.
- [ ] 2.5 RED: add `backend/tests/test_document_persistence.py` for
  function-oriented DB helpers: creating an `INIT` row, committing and refreshing
  a generated `doc_id`, marking `UPLOADED`, starting `CONVERTING`, marking
  `CONVERTED`, rolling back to `UPLOADED`, and raising state conflict on
  zero-row expected-state updates.
- [ ] 2.6 RED: run `uv run --extra dev pytest tests/test_document_persistence.py -q`
  and confirm it fails because the document model and persistence functions are
  absent.
- [ ] 2.7 GREEN: add `models.py` and focused persistence functions in
  `repository.py`; do not introduce a repository class unless a later test
  proves a real lifecycle need.
- [ ] 2.8 GREEN: rerun `uv run --extra dev pytest tests/test_document_persistence.py -q`
  and confirm lifecycle and conflict tests pass.

## 3. Upload API Validation and Error Envelope

- [ ] 3.1 RED: add `backend/tests/test_document_upload_api_validation.py` for
  `POST /api/v1/document/upload` missing `file`, `upload_user`, or
  `accessible_by`, returning HTTP 422 with `APIResponse.code=422`,
  `message=request validation failed`, and `data=null`.
- [ ] 3.2 RED: extend the same file for blank `upload_user`, blank
  `accessible_by`, empty file, missing/blank filename, unreadable stream, and
  oversized file returning the specified 400 or 413 envelope before any
  `knowledge_document` insert.
- [ ] 3.3 RED: add a path-like filename case proving `doc_title` and object-key
  suffixes use a safe basename and raw path segments are not used as object-key
  prefixes.
- [ ] 3.4 RED: run `uv run --extra dev pytest tests/test_document_upload_api_validation.py -q`
  and confirm it fails because the document route and validation boundary are
  absent.
- [ ] 3.5 GREEN: add `router.py`, `schemas.py`, and route-level validation/error
  mapping. The router must call module-level workflow functions rather than a
  stateless service class.
- [ ] 3.6 GREEN: rerun `uv run --extra dev pytest tests/test_document_upload_api_validation.py -q`
  and confirm validation tests pass without MinIO or MinerU calls.

## 4. File Type Detection

- [ ] 4.1 RED: add `backend/tests/test_document_file_type.py` covering Magika PDF
  detection, Markdown detection, `.md` / `.markdown` / `.txt` generic text
  fallback, unsupported file type, and Magika runtime failure.
- [ ] 4.2 RED: run `uv run --extra dev pytest tests/test_document_file_type.py -q`
  and confirm it fails because detection functions are absent.
- [ ] 4.3 GREEN: add `file_types.py` with `detect_document_file_type(...)` and
  the smallest business enum/value shape needed by the workflow.
- [ ] 4.4 GREEN: rerun `uv run --extra dev pytest tests/test_document_file_type.py -q`
  and confirm detection tests pass.

## 5. MinIO Storage Helpers

- [ ] 5.1 RED: add `backend/tests/test_document_storage.py` covering bucket
  creation, object keys under `documents/{doc_id}/original/{safe_filename}`,
  converted Markdown keys, asset keys, URL construction from
  `MINIO_PUBLIC_BASE_URL`, and threadpool execution for synchronous SDK calls.
- [ ] 5.2 RED: run `uv run --extra dev pytest tests/test_document_storage.py -q`
  and confirm it fails because the storage helpers are absent.
- [ ] 5.3 GREEN: add `storage.py` with document object-key helpers and a thin
  storage adapter or functions around the official MinIO SDK. Keep MinIO SDK
  client ownership in infrastructure.
- [ ] 5.4 GREEN: rerun `uv run --extra dev pytest tests/test_document_storage.py -q`
  and confirm storage tests pass with a fake or mocked MinIO client.

## 6. Plain Text Upload Workflow

- [ ] 6.1 RED: add `backend/tests/test_document_plain_text_upload.py` covering a
  `.md` upload that persists `INIT`, uploads the original, sets `doc_url`, sets
  `converted_doc_url=doc_url`, transitions to `CONVERTED`, and returns HTTP 200
  document metadata.
- [ ] 6.2 RED: extend the same file for MinIO original upload failure returning
  HTTP 502 `document storage failed`, keeping status `INIT`, and not calling any
  conversion function.
- [ ] 6.3 RED: run `uv run --extra dev pytest tests/test_document_plain_text_upload.py -q`
  and confirm it fails because `upload_document(...)` orchestration is absent.
- [ ] 6.4 GREEN: add `workflow.py` with `upload_document(...)` as a module-level
  async function implementing the plain text path without holding a DB
  transaction across MinIO calls.
- [ ] 6.5 GREEN: rerun `uv run --extra dev pytest tests/test_document_plain_text_upload.py -q`
  and confirm the plain text success and storage failure tests pass.

## 7. PDF Conversion Success

- [ ] 7.1 RED: add `backend/tests/test_document_pdf_conversion.py` covering
  MinerU `POST /file_parse`, safe ZIP extraction, image upload under
  `documents/{doc_id}/assets/`, final Markdown upload under
  `documents/{doc_id}/converted/document.md`, relative image link rewriting to
  full MinIO URLs, and first-version alt text `图片描述`.
- [ ] 7.2 RED: add multiple-Markdown selection tests: basename match wins,
  matching parent directory wins second, and lexicographically first normalized
  Markdown path wins last.
- [ ] 7.3 RED: add an API-level PDF success test proving the endpoint persists
  `INIT`, uploads the original, transitions `UPLOADED -> CONVERTING -> CONVERTED`,
  sets `converted_doc_url` to the final Markdown URL, and returns HTTP 200.
- [ ] 7.4 RED: run `uv run --extra dev pytest tests/test_document_pdf_conversion.py -q`
  and confirm it fails because MinerU conversion and PDF workflow functions are
  absent.
- [ ] 7.5 GREEN: add `mineru.py`, `markdown.py`, and PDF workflow functions for
  the successful path using local temporary ZIP processing before converted
  object uploads.
- [ ] 7.6 GREEN: rerun `uv run --extra dev pytest tests/test_document_pdf_conversion.py -q`
  and confirm PDF success tests pass.

## 8. PDF Failure and Rollback

- [ ] 8.1 RED: add `backend/tests/test_document_pdf_failures.py` covering MinerU
  request failure, corrupted ZIP, unsafe ZIP path traversal, duplicate
  normalized ZIP paths, no usable Markdown, Markdown rewrite failure, converted
  asset upload failure, converted Markdown upload failure, and expected-state
  conflict.
- [ ] 8.2 RED: assert each conversion failure after original upload returns HTTP
  502 `document conversion failed`, leaves the original `doc_url`, restores or
  keeps status `UPLOADED`, and does not set `converted_doc_url`.
- [ ] 8.3 RED: add rollback failure coverage proving conversion failure after
  `CONVERTING` returns HTTP 500 `document state rollback failed` when restoring
  `UPLOADED` fails.
- [ ] 8.4 RED: run `uv run --extra dev pytest tests/test_document_pdf_failures.py -q`
  and confirm it fails for the missing failure handling.
- [ ] 8.5 GREEN: implement PDF failure normalization, expected-state conflict
  mapping to HTTP 409 `document state conflict`, and rollback failure mapping to
  HTTP 500 `document state rollback failed`.
- [ ] 8.6 GREEN: rerun `uv run --extra dev pytest tests/test_document_pdf_failures.py -q`
  and confirm all failure matrix tests pass.

## 9. Contract Verification

- [ ] 9.1 Run focused document tests:
  `uv run --extra dev pytest tests/test_document_config.py tests/test_document_resource_ownership.py tests/test_document_migration.py tests/test_document_persistence.py tests/test_document_upload_api_validation.py tests/test_document_file_type.py tests/test_document_storage.py tests/test_document_plain_text_upload.py tests/test_document_pdf_conversion.py tests/test_document_pdf_failures.py -q`.
- [ ] 9.2 Run the full backend suite: `uv run --extra dev pytest -q`.
- [ ] 9.3 Run migration verification from a clean development database if the
  configured database is available: `uv run alembic downgrade base && uv run alembic upgrade head`.
- [ ] 9.4 Run OpenSpec validation: `openspec validate add-document-upload --strict`.
- [ ] 9.5 Confirm `openspec status --change add-document-upload` shows the tasks
  tracked with implementation still pending until the RED/GREEN slices are
  completed.
