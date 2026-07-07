## ADDED Requirements

### Requirement: DATA_QUERY spreadsheet upload tableName validation
The system SHALL require a valid `tableName` field for DATA_QUERY Excel and CSV uploads.

#### Scenario: DATA_QUERY spreadsheet upload accepts tableName
- **WHEN** a client uploads an Excel or CSV file with `knowledgeBaseType` equal to `DATA_QUERY`
- **AND** multipart form data includes `tableName`
- **AND** `tableName` contains only lowercase English letters, digits, and underscores
- **THEN** the system SHALL validate the request as a DATA_QUERY spreadsheet upload request

#### Scenario: Missing DATA_QUERY tableName is rejected
- **WHEN** a client uploads a file with `knowledgeBaseType` equal to `DATA_QUERY`
- **AND** multipart form data does not include a non-blank `tableName`
- **THEN** the system SHALL return HTTP 400 with `APIResponse.code` equal to `400`
- **AND** the response message SHALL be `invalid upload request`
- **AND** the system MUST NOT create a `knowledge_document` record
- **AND** the system MUST NOT create a `table_meta` record

#### Scenario: Invalid DATA_QUERY tableName is rejected
- **WHEN** a client uploads a file with `knowledgeBaseType` equal to `DATA_QUERY`
- **AND** `tableName` contains a character other than lowercase English letters, digits, or underscores
- **THEN** the system SHALL return HTTP 400 with `APIResponse.code` equal to `400`
- **AND** the response message SHALL be `invalid upload request`
- **AND** the system MUST NOT create a `knowledge_document` record
- **AND** the system MUST NOT create a `table_meta` record

#### Scenario: DOCUMENT_SEARCH upload does not require tableName
- **WHEN** a client uploads a supported file with `knowledgeBaseType` equal to `DOCUMENT_SEARCH`
- **AND** multipart form data omits `tableName`
- **THEN** the system SHALL NOT reject the request because `tableName` is absent
- **AND** the upload workflow MUST NOT create a `table_meta` reservation for that document

### Requirement: DATA_QUERY spreadsheet upload override option
The system SHALL accept optional destructive override intent for DATA_QUERY spreadsheet uploads.

#### Scenario: isOverride defaults to false
- **WHEN** a client uploads a DATA_QUERY Excel or CSV file
- **AND** multipart form data omits `isOverride`
- **THEN** the system SHALL treat `isOverride` as `false`

#### Scenario: DATA_QUERY upload options are stored in extension
- **WHEN** a DATA_QUERY Excel or CSV upload is accepted
- **THEN** `knowledge_document.extension` SHALL include `tableName`
- **AND** `knowledge_document.extension` SHALL include `isOverride`

#### Scenario: DOCUMENT_SEARCH upload ignores override option
- **WHEN** a client uploads a supported file with `knowledgeBaseType` equal to `DOCUMENT_SEARCH`
- **THEN** the upload workflow SHALL NOT create or override `table_meta` because of `isOverride`

### Requirement: DATA_QUERY spreadsheet upload type boundary
The system SHALL accept only Excel and CSV files for DATA_QUERY uploads in this change.

#### Scenario: DATA_QUERY non-spreadsheet upload is rejected
- **WHEN** a client uploads a supported non-spreadsheet file with `knowledgeBaseType` equal to `DATA_QUERY`
- **THEN** the system SHALL return HTTP 415 with `APIResponse.code` equal to `415`
- **AND** the response message SHALL be `unsupported file type`
- **AND** the system MUST NOT create a `knowledge_document` record
- **AND** the system MUST NOT create a `table_meta` record

### Requirement: DATA_QUERY tableName reservation and override
The system SHALL reserve each DATA_QUERY logical table name during upload before asynchronous ingestion is dispatched.

#### Scenario: New DATA_QUERY tableName is reserved
- **WHEN** a DATA_QUERY Excel or CSV upload has a valid new `tableName`
- **AND** no `table_meta` row exists for the same uploader namespace and `tableName`
- **THEN** the system SHALL create a `knowledge_document` record with status `INIT`
- **AND** the system SHALL create one `table_meta` reservation linked to that document
- **AND** the reservation SHALL use the uploader namespace and the user-provided `tableName`

#### Scenario: Duplicate DATA_QUERY tableName is rejected by default
- **WHEN** a DATA_QUERY Excel or CSV upload has a valid `tableName`
- **AND** `isOverride` is false
- **AND** a `table_meta` row already exists for the same uploader namespace and `tableName`
- **THEN** the system SHALL return HTTP 409 with `APIResponse.code` equal to `409`
- **AND** the response message SHALL be `table name conflict`
- **AND** the system MUST NOT create a second `knowledge_document` record for that `tableName`
- **AND** the system MUST NOT create a second `table_meta` record for that `tableName`

#### Scenario: Duplicate DATA_QUERY tableName is destructively overridden
- **WHEN** a DATA_QUERY Excel or CSV upload has a valid `tableName`
- **AND** `isOverride` is true
- **AND** a `table_meta` row already exists for the same uploader namespace and `tableName`
- **THEN** the system SHALL drop the old generated physical table for that `tableName` when it exists
- **AND** the system SHALL delete the old `table_meta` row
- **AND** the system SHALL create a new `knowledge_document` record with status `INIT`
- **AND** the system SHALL create a new `table_meta` reservation linked to the new document

#### Scenario: Override does not restore old data after later failure
- **WHEN** a DATA_QUERY override upload deletes the old generated physical table and old `table_meta`
- **AND** original file storage, Kafka dispatch, or later worker import fails
- **THEN** the system SHALL NOT restore the old generated physical table
- **AND** the system SHALL NOT restore the old `table_meta` row

#### Scenario: Failed original storage releases new tableName reservation
- **WHEN** a DATA_QUERY upload creates a new `table_meta` reservation
- **AND** original file upload to MinIO fails before the new document reaches `UPLOADED`
- **THEN** the system SHALL leave the new document in `INIT` or remove the failed new document according to the existing upload failure behavior
- **AND** the system SHALL remove the new `table_meta` reservation for that failed upload

### Requirement: DATA_QUERY upload locking
The system SHALL protect DATA_QUERY tableName reservation and destructive override cleanup with a user-level non-waiting lock.

#### Scenario: DATA_QUERY upload lock is acquired before reservation
- **WHEN** a DATA_QUERY Excel or CSV upload reaches tableName reservation or override handling
- **THEN** the system SHALL acquire a Redis lock named `data_query_upload:{namespace}`
- **AND** it SHALL acquire the lock without waiting
- **AND** it SHALL release the lock after reservation, original storage, status update, and dispatch handling finish

#### Scenario: Busy DATA_QUERY upload lock is rejected
- **WHEN** another request already holds `data_query_upload:{namespace}`
- **THEN** the system SHALL return HTTP 409 with `APIResponse.code` equal to `409`
- **AND** the response message SHALL be `data query upload busy`
- **AND** the system MUST NOT create a `knowledge_document` record
- **AND** the system MUST NOT create a `table_meta` record

#### Scenario: DATA_QUERY upload lock failure is reported
- **WHEN** the system cannot reach Redis or cannot evaluate the DATA_QUERY upload lock
- **THEN** the system SHALL return HTTP 503 with `APIResponse.code` equal to `503`
- **AND** the response message SHALL be `data query upload lock unavailable`
- **AND** the system MUST NOT create a `knowledge_document` record
- **AND** the system MUST NOT create a `table_meta` record

## MODIFIED Requirements

### Requirement: Knowledge document schema
The system SHALL persist document metadata in `knowledge_document` with precise schema constraints.

#### Scenario: Knowledge document table exists after migration
- **WHEN** Alembic migrations are applied
- **THEN** the database SHALL contain a `knowledge_document` table

#### Scenario: Knowledge document table columns are defined
- **WHEN** the `knowledge_document` table is inspected
- **THEN** `doc_id` SHALL be a `BIGINT` primary key generated by the application Snowflake ID generator
- **AND** `doc_title` SHALL be `VARCHAR(1024) NOT NULL`
- **AND** `upload_user` SHALL be `VARCHAR(255) NOT NULL`
- **AND** `description` SHALL be `TEXT NOT NULL`
- **AND** `knowledge_base_type` SHALL be `VARCHAR(64) NOT NULL`
- **AND** `extension` SHALL be a PostgreSQL `JSONB NOT NULL` column with an empty-object default
- **AND** `doc_url` SHALL be `VARCHAR(2048) NULL`
- **AND** `file_type` SHALL be `VARCHAR(32) NOT NULL`
- **AND** `converted_doc_url` SHALL be `VARCHAR(2048) NULL`
- **AND** `status` SHALL be `VARCHAR(32) NOT NULL DEFAULT 'INIT'`
- **AND** `accessible_by` SHALL be `VARCHAR(1024) NOT NULL`
- **AND** `created_at` SHALL be a timezone-aware timestamp with a current-time default
- **AND** `updated_at` SHALL be a timezone-aware timestamp with a current-time default

#### Scenario: Knowledge document status is constrained
- **WHEN** a `knowledge_document` record is persisted
- **THEN** `status` SHALL be one of `INIT`, `UPLOADED`, `CONVERTING`, `CONVERTED`, `CHUNKED`, `VECTOR_STORED`, or `STORED`

#### Scenario: Knowledge document indexes are present
- **WHEN** migrations are applied
- **THEN** the table SHALL have indexes supporting lookups by `status`, `upload_user`, and `created_at`

### Requirement: Spreadsheet origin conversion
The system SHALL treat supported Excel and CSV document-search uploads as already converted content by reusing the original object URL.

#### Scenario: Excel document-search upload completes conversion by reusing origin
- **WHEN** a supported Excel file has been uploaded to MinIO
- **AND** the document `knowledge_base_type` is `DOCUMENT_SEARCH`
- **THEN** the Excel converter SHALL return the original `doc_url`
- **AND** the converter MUST NOT call MinerU
- **AND** the converter MUST NOT upload an intermediate converted Markdown or HTML object

#### Scenario: CSV document-search upload completes conversion by reusing origin
- **WHEN** a supported CSV file has been uploaded to MinIO
- **AND** the document `knowledge_base_type` is `DOCUMENT_SEARCH`
- **THEN** the Excel converter SHALL return the original `doc_url`
- **AND** the converter MUST NOT call MinerU
- **AND** the converter MUST NOT upload an intermediate converted Markdown or HTML object
