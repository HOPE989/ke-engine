## 1. Test Coverage First

- [x] 1.1 Add upload validation tests for DATA_QUERY `tableName` required, format validation, DOCUMENT_SEARCH without `tableName`, `isOverride` defaulting, and DATA_QUERY non-spreadsheet rejection.
- [x] 1.2 Add upload conflict and override tests proving duplicate `(namespace, tableName)` returns HTTP 409 when `isOverride=false` and destructively removes old table metadata when `isOverride=true`.
- [x] 1.3 Add upload-lock tests for `data_query_upload:{namespace}` busy behavior and lock infrastructure failure mapping.
- [x] 1.4 Add migration/model tests for `STORED` status, `knowledge_document.extension`, and `table_meta` columns, indexes, foreign key, and uniqueness constraints.
- [x] 1.5 Add DATA_QUERY parser tests for Excel one-data-sheet acceptance, empty workbook rejection, header-only rejection, multiple-data-sheet rejection, empty extra sheet ignoring, CSV single-table behavior, and CSV without data rows rejection.
- [x] 1.6 Add ingestion workflow tests for generated table names, `col_001` column mapping, all-`TEXT` data columns, single-table `columns_info` shape, and generated DDL storage.
- [x] 1.7 Add transaction tests proving import failure rolls back physical table creation, inserted rows, metadata updates, and document `STORED` transition.
- [x] 1.8 Add worker tests for document-lock busy retry behavior, already-`STORED` idempotency, existing-physical-table no-drop behavior, and DOCUMENT_SEARCH spreadsheet regression.

## 2. Schema And Models

- [x] 2.1 Add an Alembic migration that extends `knowledge_document.status` to include `STORED`.
- [x] 2.2 Add an Alembic migration that adds `knowledge_document.extension` as JSONB with an empty-object default.
- [x] 2.3 Add an Alembic migration for `table_meta` with `namespace`, `document_id`, `table_name`, `description`, `create_sql`, `columns_info`, timestamps, and required constraints.
- [x] 2.4 Update SQLAlchemy models and enums for `DocumentStatus.STORED`, `KnowledgeDocument.extension`, and `TableMeta`.
- [x] 2.5 Add repository methods for DATA_QUERY metadata reservation, lookup by document, duplicate detection, destructive override cleanup, reservation cleanup, and transactional metadata update.

## 3. Upload Boundary

- [x] 3.1 Add optional multipart `tableName` and `isOverride` to `POST /api/v1/document/upload`.
- [x] 3.2 Extend request validation to normalize and validate DATA_QUERY `tableName` using `^[a-z0-9_]+$` and to default `isOverride` to false.
- [x] 3.3 Store DATA_QUERY upload options in `knowledge_document.extension` as `tableName` and `isOverride`.
- [x] 3.4 Reject DATA_QUERY uploads whose detected file type is not Excel or CSV before document or metadata persistence.
- [x] 3.5 Add a Redis lock factory for `data_query_upload:{namespace}` and use it around DATA_QUERY reservation, override cleanup, original storage, status update, and dispatch handling.
- [x] 3.6 Reserve `(namespace, tableName)` during DATA_QUERY upload and map uniqueness violations with `isOverride=false` to HTTP 409 `table name conflict`.
- [x] 3.7 Implement destructive override for `isOverride=true` by dropping the old generated physical table when present, deleting old `table_meta`, and creating a new document plus reservation.
- [x] 3.8 Ensure failed original-file storage removes the new DATA_QUERY metadata reservation without attempting to restore overridden old data.

## 4. DATA_QUERY Spreadsheet Ingestion

- [x] 4.1 Add a DATA_QUERY spreadsheet parser that returns one table-shaped dataset and rejects empty, header-only, or multi-data-sheet inputs.
- [x] 4.2 Implement generated physical table naming using the fixed DATA_QUERY prefix, namespace token, and logical `tableName`.
- [x] 4.3 Implement generated column mapping as `col_001`, `col_002`, and all PostgreSQL `TEXT` types while preserving original headers in single-table `columns_info`.
- [x] 4.4 Implement safe PostgreSQL DDL and DML generation with backend-generated identifiers and parameter-bound row values.
- [x] 4.5 Implement the transactional import workflow that creates the physical table, inserts data, updates `table_meta`, and marks the document `STORED`.
- [x] 4.6 Ensure failed DATA_QUERY import leaves the document `UPLOADED` and commits no partial generated table, row data, or metadata.
- [x] 4.7 Ensure an existing generated physical table during worker import is treated as a consistency error and is not automatically dropped or rebuilt.

## 5. Worker Routing And Idempotency

- [x] 5.1 Route Excel/CSV conversion worker processing by both `file_type` and `knowledge_base_type`.
- [x] 5.2 Keep DOCUMENT_SEARCH Excel/CSV on the existing origin-URL conversion path.
- [x] 5.3 Run DATA_QUERY Excel/CSV through the relational ingestion path without setting `converted_doc_url`.
- [x] 5.4 Keep DATA_QUERY worker processing under the per-document conversion lock `document:{doc_id}:convert`.
- [x] 5.5 Make DATA_QUERY document-lock busy attempts retryable by leaving the Kafka message uncommitted.
- [x] 5.6 Make already-`STORED` DATA_QUERY documents terminal and safe to commit without touching the physical table.

## 6. Verification

- [x] 6.1 Run `cd backend; uv run pytest tests/test_document_upload_api_validation.py tests/test_document_migration.py`.
- [x] 6.2 Run `cd backend; uv run pytest tests/test_document_conversion_worker.py tests/test_document_converters.py`.
- [x] 6.3 Run `cd backend; uv run pytest tests/test_document_data_query_spreadsheet_ingestion.py` after adding the new workflow tests.
- [x] 6.4 Run `cd backend; uv run pytest` for full backend regression.
- [x] 6.5 Run `openspec validate add-data-query-spreadsheet-ingestion --strict`.
