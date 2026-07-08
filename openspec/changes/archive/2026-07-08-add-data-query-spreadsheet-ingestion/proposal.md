## Why

DATA_QUERY Excel and CSV uploads currently share the document-search spreadsheet path, but these uploads represent structured tabular data that should be queryable through a relational database table rather than RAG chunks. This change introduces a dedicated ingestion path aligned with LLMentor `a5882d93`: one DATA_QUERY spreadsheet upload creates one dynamic PostgreSQL table and one `table_meta` record.

## What Changes

- Add a DATA_QUERY spreadsheet ingestion workflow for Excel and CSV files.
- Require DATA_QUERY spreadsheet uploads to include a user-provided `tableName`.
- Validate `tableName` as lowercase letters, digits, and underscores only.
- Store DATA_QUERY upload options in `knowledge_document.extension`, including `tableName` and optional `isOverride`.
- Enforce `tableName` uniqueness within the uploader namespace by default.
- Support explicit destructive override when `isOverride=true`.
- Add `STORED` as the terminal document status for successfully ingested DATA_QUERY spreadsheets.
- Add table metadata persistence for DATA_QUERY datasets, including generated DDL and column mapping JSON.
- Map each DATA_QUERY Excel or CSV upload to exactly one generated PostgreSQL table.
- Use generated physical column names (`col_001`, `col_002`, ...) and preserve original headers in metadata.
- Process DATA_QUERY spreadsheet ingestion asynchronously after original file upload.
- Protect DATA_QUERY upload reservation and override cleanup with a user-level, non-waiting upload lock.
- Keep DOCUMENT_SEARCH Excel/CSV conversion and chunking behavior unchanged.

## Capabilities

### New Capabilities
- `data-query-spreadsheet-ingestion`: Defines DATA_QUERY Excel/CSV single-table relational ingestion, table metadata, generated table/column naming, transactions, worker idempotency, and terminal state behavior.

### Modified Capabilities
- `document-upload`: Adds DATA_QUERY upload validation for `tableName`, optional `isOverride`, extension persistence, uniqueness/override reservation, and the `STORED` document lifecycle state.

## Impact

- Backend API request validation for `POST /api/v1/document/upload`.
- Document models, schemas, migrations, and status constraints.
- `knowledge_document.extension` persistence for DATA_QUERY upload options.
- Conversion worker routing for Excel/CSV when `knowledge_base_type` is `DATA_QUERY`.
- PostgreSQL schema changes for DATA_QUERY `table_meta` metadata.
- Redis lock usage in the DATA_QUERY upload path.
- Tests for upload validation, uniqueness, override behavior, metadata persistence, dynamic table creation, worker idempotency, transaction rollback, and DOCUMENT_SEARCH regression coverage.
