## Context

The document module already accepts `DOCUMENT_SEARCH` and `DATA_QUERY` knowledge base types, stores uploaded originals in MinIO, and dispatches asynchronous conversion work through Kafka. Excel and CSV are currently treated as document-search inputs: conversion reuses the original object URL, and the chunking phase later parses the file into compact HTML table chunks for vector search.

For `DATA_QUERY`, the same file types have different meaning. The uploaded spreadsheet is structured data and must become a relational table plus metadata for later Text2SQL-style retrieval. This design intentionally aligns the first version with LLMentor `a5882d93`: one DATA_QUERY upload creates one physical table and one `table_meta` row. It does not introduce document versions, active table pointers, multi-sheet datasets, or non-destructive table switching.

The upload API remains asynchronous. The request validates and stores the original file, reserves or overrides table metadata, and dispatches a worker. The worker performs the database import and marks the document `STORED`.

## Goals / Non-Goals

**Goals:**
- Add a dedicated Excel/CSV `DATA_QUERY` ingestion path that writes one PostgreSQL table per upload.
- Require and validate a user-provided logical `tableName` for `DATA_QUERY` spreadsheet uploads.
- Store DATA_QUERY upload options in `knowledge_document.extension`, including `tableName` and `isOverride`.
- Enforce `tableName` uniqueness within the uploader namespace by default.
- Allow explicit destructive overwrite when `isOverride=true`.
- Persist one `table_meta` row per DATA_QUERY physical table.
- Use stable generated physical column names (`col_001`, `col_002`, ...) and preserve original headers in JSON metadata.
- Mark successful DATA_QUERY spreadsheet ingestion as `STORED`.

**Non-Goals:**
- Do not support one Excel workbook producing multiple physical tables.
- Do not add document versioning, active/inactive table versions, rollback to previous table data, or table history.
- Do not support automatic same-name replacement when `isOverride` is absent or false.
- Do not add schema-compatible old-data replacement.
- Do not add user-facing row insert/update/delete behavior.
- Do not implement Text2SQL retrieval in this change.
- Do not change `DOCUMENT_SEARCH` Excel/CSV conversion, chunking, embedding, or vector-storage behavior.
- Do not infer column types from spreadsheet data in the first version.

## Decisions

### 1. One DATA_QUERY upload creates one physical table

The MVP data model is:

```text
one DATA_QUERY document -> one table_meta row -> one generated PostgreSQL table
```

Excel files must resolve to exactly one importable worksheet. Fully empty worksheets may be ignored, but a workbook with more than one worksheet containing data is rejected. CSV files always resolve to one importable table.

Alternatives considered:
- Map every Excel sheet to a physical table. This creates table naming, metadata shape, transaction, and Text2SQL prompt complexity that is not needed for the first version.
- Silently import only the first Excel sheet like LLMentor's EasyExcel default. This is simple but can surprise users who upload multi-sheet workbooks.

Chosen rationale: a single-table model matches LLMentor `a5882d93` and Bailian-style DATA_QUERY knowledge bases while keeping first-version ownership and retry behavior clear.

### 2. `namespace + tableName` is the logical table identity

The logical identity of a DATA_QUERY table is `(namespace, tableName)`, where the MVP namespace is derived from `upload_user`. By default, the same namespace cannot reuse `tableName` for a second document.

Alternatives considered:
- Use `doc_id` as the identity. This avoids conflicts but makes user-provided table names non-unique aliases and allows multiple current DATA_QUERY tables with the same name.
- Include `doc_id` in physical table names and use an active pointer. This is more robust for non-destructive replacement, but it introduces version-like semantics that are out of scope.

Chosen rationale: `tableName` is what the user names for querying, so it should be unique in the user's namespace unless the user explicitly requests destructive override.

### 3. Override is explicit and destructive

`isOverride` is an optional DATA_QUERY upload parameter stored in `knowledge_document.extension`. The default is false.

When `(namespace, tableName)` exists and `isOverride=false`, upload fails with `table name conflict`.

When `(namespace, tableName)` exists and `isOverride=true`, the upload path deletes the old generated physical table and old `table_meta` row before reserving the same logical `tableName` for the new document. This is destructive: the old table is not restored if later MinIO upload, Kafka dispatch, or worker import fails.

Alternatives considered:
- Implement schema-compatible delete/insert replacement. That belongs to a later multi-version or same-logical-table update model.
- Implement active-pointer switching with `doc_id` in the physical table name. That avoids data loss but adds a versioning mechanism.

Chosen rationale: matching LLMentor's override concept is useful, but the first version keeps the behavior explicit and simple.

### 4. Reserve or override during upload

The upload workflow owns table-name reservation. It creates the `knowledge_document` row and the `table_meta` reservation before asynchronous ingestion is dispatched. A unique constraint on `(namespace, table_name)` prevents two simultaneous uploads from both claiming the same DATA_QUERY name.

DATA_QUERY upload reservation and override cleanup are protected by a user-level non-waiting Redis lock:

```text
data_query_upload:{namespace}
```

If the lock is busy, the API returns a busy error. If the lock is acquired but the database uniqueness check fails and `isOverride=false`, the API returns `table name conflict`.

Alternatives considered:
- Check uniqueness only in the worker. This permits two same-name uploads to be accepted and fails late.
- Use the same lock key for upload and import. The two phases have different failure semantics, and the worker can be safely scoped to the document lock in the single-table model.

Chosen rationale: early reservation gives immediate user feedback and keeps the worker from making override decisions.

### 5. Keep one `table_meta` row per DATA_QUERY table

`table_meta` represents one generated physical table. The row stores the uploader namespace, owning document id, logical table name, generated DDL, and column metadata. `columns_info` is a JSON object rather than a multi-sheet array:

```json
{
  "originalSheetName": "Sales",
  "physicalTableName": "dq_user_xxx_orders",
  "columns": [
    {"ordinal": 1, "header": "Customer", "columnName": "col_001", "type": "TEXT"}
  ]
}
```

Alternatives considered:
- One metadata row per sheet. No longer needed because the MVP does not produce multiple tables per upload.
- Split parent dataset and child table metadata tables. This is unnecessary for one-table DATA_QUERY uploads.

Chosen rationale: one row naturally enforces `(namespace, tableName)` uniqueness and is enough for MVP Text2SQL schema assembly.

### 6. Generate safe physical names and columns

Physical table names are generated by the backend:

```text
dq_{namespace_token}_{tableName}
```

The `namespace_token` must be generated from the namespace using a deterministic safe representation, not raw unbounded user text. Columns are generated as `col_001`, `col_002`, ... and all spreadsheet data columns are PostgreSQL `TEXT`.

Alternatives considered:
- Use original headers as physical column names. This creates problems with empty headers, duplicate names, spaces, non-ASCII names, keywords, long identifiers, and changing sheet header text.
- Let users supply the physical table name. The product only needs a logical table name; physical names should stay backend-owned.

Chosen rationale: generated identifiers avoid SQL injection and quoting complexity while preserving user-facing labels in metadata.

### 7. Route by file type and knowledge base type

The converter/processor selection for Excel and CSV must consider `knowledge_base_type`. `DOCUMENT_SEARCH` Excel/CSV continues to reuse the original URL and later chunk into HTML table segments. `DATA_QUERY` Excel/CSV downloads the original bytes, parses the single table, writes relational data, and does not set `converted_doc_url`.

Alternatives considered:
- Keep factory keyed only by file type and branch inside `ExcelConverter`.
- Add a separate worker topic.

Chosen rationale: a dedicated DATA_QUERY handler keeps the two spreadsheet meanings explicit while preserving the existing Kafka event and worker runtime.

### 8. Worker import is transaction-scoped and does not drop/rebuild for retry

The worker uses the existing per-document conversion lock:

```text
document:{doc_id}:convert
```

The worker only imports when the document is `UPLOADED`, the `table_meta` row belongs to the same `document_id`, and the generated physical table does not already exist. It creates the table, inserts rows, updates `table_meta`, and marks the document `STORED` in one PostgreSQL transaction.

If the transaction fails, PostgreSQL rolls back the DDL, DML, metadata update, and status update together. If Kafka redelivers after a successful commit, the worker sees `STORED` and treats the message as already complete. If an `UPLOADED` document's target physical table already exists, the worker treats it as a consistency error and does not automatically drop it.

Alternatives considered:
- Drop and rebuild on same-document retry. This is not appropriate for the new-table model and could destroy data in a state that should require explicit override or manual cleanup.
- Add a user-level import lock. With one document owning one table and `(namespace, tableName)` reserved during upload, the per-document lock and database constraints are enough for first-version correctness.

Chosen rationale: worker retry should be idempotent through transaction rollback and `STORED` no-op behavior, not through destructive rebuild.

## Risks / Trade-offs

- Override can delete old data before the new import succeeds -> This is explicit destructive behavior; users must pass `isOverride=true`.
- A failed override can leave no active table for that `tableName` -> Accept for MVP; non-destructive replacement requires active-pointer/version design.
- Upload user-level lock limits concurrent DATA_QUERY uploads for one namespace -> Accept for MVP; later narrow lock scope if needed.
- A permanently failing import can leave a reserved `tableName` tied to an `UPLOADED` document -> Add retry/admin cleanup or failure state later if needed.
- Dynamic SQL is required for generated tables -> Only compose SQL from validated/generated identifiers and parameterize row values.
- Existing old documents may remain `STORED` after override removes their physical table -> Retrieval must be driven by current `table_meta`, not old document rows.

## Migration Plan

1. Add `STORED` to the `knowledge_document.status` enum constraint and ORM enum.
2. Add `knowledge_document.extension` for JSON upload options.
3. Add a `table_meta` table with `namespace`, `document_id`, `table_name`, `description`, `create_sql`, `columns_info`, and timestamps.
4. Add unique constraints for `(namespace, table_name)` and `document_id`.
5. Add runtime/repository APIs for DATA_QUERY reservation, destructive override cleanup, metadata lookup, and transactional metadata update.
6. Add the DATA_QUERY spreadsheet ingestion workflow and worker routing.
7. Add tests before enabling the path in normal worker execution.

Rollback removes the DATA_QUERY metadata table, removes `extension`, and removes `STORED` from the document status constraint only after no documents remain in `STORED`.

## Open Questions

- The MVP namespace is `upload_user`. Production should replace this with tenant/user identity when authentication exists.
- There is no user-facing retry or cleanup endpoint in this change. Failed imports remain `UPLOADED` with their `tableName` reservation held by the same document unless an explicit override upload removes it.
