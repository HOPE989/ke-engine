## Purpose

Define the document upload and conversion workflow, including validation, storage, lifecycle persistence, conversion, and configuration requirements.

## Requirements

### Requirement: Document upload error envelope
The system SHALL return document upload failures through the shared `APIResponse` error envelope.

#### Scenario: Document upload error shape
- **WHEN** the document upload endpoint returns HTTP 400, 409, 413, 415, 422, 500, or 502
- **THEN** the response body SHALL contain `code` equal to the HTTP status code
- **AND** the response body SHALL contain a stable short `message`
- **AND** the response body SHALL contain `data` set to `null`
- **AND** the response body MUST NOT include secret values, local file paths, stack traces, MinIO credentials, raw provider exceptions, or full MinerU response bodies

### Requirement: Document upload endpoint
The system SHALL expose a synchronous document upload endpoint at `POST /api/v1/document/upload`.

#### Scenario: Upload request accepts required multipart fields
- **WHEN** a client sends multipart form data with `file`, `upload_user`, and `accessible_by`
- **THEN** the system SHALL validate the request as a document upload request

#### Scenario: Missing upload file is rejected
- **WHEN** a client sends `POST /api/v1/document/upload` without `file`
- **THEN** the system SHALL return HTTP 422 with `APIResponse.code` equal to `422`
- **AND** the response message SHALL be `request validation failed`

#### Scenario: Missing upload user is rejected
- **WHEN** a client sends `POST /api/v1/document/upload` without `upload_user`
- **THEN** the system SHALL return HTTP 422 with `APIResponse.code` equal to `422`
- **AND** the response message SHALL be `request validation failed`

#### Scenario: Missing accessible scope is rejected
- **WHEN** a client sends `POST /api/v1/document/upload` without `accessible_by`
- **THEN** the system SHALL return HTTP 422 with `APIResponse.code` equal to `422`
- **AND** the response message SHALL be `request validation failed`

#### Scenario: Blank upload user is rejected before persistence
- **WHEN** a client sends `upload_user` that is empty or only whitespace
- **THEN** the system SHALL return HTTP 400 with `APIResponse.code` equal to `400`
- **AND** the response message SHALL be `invalid upload request`
- **AND** the system MUST NOT create a `knowledge_document` record

#### Scenario: Blank accessible scope is rejected before persistence
- **WHEN** a client sends `accessible_by` that is empty or only whitespace
- **THEN** the system SHALL return HTTP 400 with `APIResponse.code` equal to `400`
- **AND** the response message SHALL be `invalid upload request`
- **AND** the system MUST NOT create a `knowledge_document` record

#### Scenario: Empty upload file is rejected before persistence
- **WHEN** a client uploads a file with zero bytes
- **THEN** the system SHALL return HTTP 400 with `APIResponse.code` equal to `400`
- **AND** the response message SHALL be `invalid upload request`
- **AND** the system MUST NOT create a `knowledge_document` record

#### Scenario: Missing file name is rejected before persistence
- **WHEN** the uploaded file has no filename after trimming whitespace
- **THEN** the system SHALL return HTTP 400 with `APIResponse.code` equal to `400`
- **AND** the response message SHALL be `invalid upload request`
- **AND** the system MUST NOT create a `knowledge_document` record

#### Scenario: Path-like file name is normalized
- **WHEN** the uploaded filename contains path separators or traversal segments
- **THEN** the system SHALL derive `doc_title` and object-key suffixes from a safe basename
- **AND** the system MUST NOT use raw path segments from the uploaded filename as object-key prefixes

#### Scenario: Upload file exceeds configured size
- **WHEN** the uploaded file is larger than `MAX_UPLOAD_SIZE_MB`
- **THEN** the system SHALL return HTTP 413 with `APIResponse.code` equal to `413`
- **AND** the response message SHALL be `file too large`
- **AND** the system MUST NOT create a `knowledge_document` record

#### Scenario: Upload file stream cannot be read
- **WHEN** the system cannot read the uploaded file stream during request validation
- **THEN** the system SHALL return HTTP 400 with `APIResponse.code` equal to `400`
- **AND** the response message SHALL be `invalid upload request`
- **AND** the system MUST NOT create a `knowledge_document` record

### Requirement: Supported file type detection
The system SHALL support PDF, Word, Markdown, plain text, Excel, and CSV inputs by using Magika-based file type detection plus narrow extension and MIME checks.

#### Scenario: PDF content is accepted
- **WHEN** Magika classifies the uploaded file as PDF or reports `application/pdf`
- **AND** Magika returns that type through its final output result
- **THEN** the system SHALL classify the upload as a PDF document

#### Scenario: Markdown content is accepted
- **WHEN** Magika classifies the uploaded file as Markdown
- **AND** Magika returns that type through its final output result
- **THEN** the system SHALL classify the upload as a plain text document

#### Scenario: Markdown and text extensions are accepted for generic text
- **WHEN** the uploaded file name ends with `.md`, `.markdown`, or `.txt`
- **AND** Magika classifies the content as text
- **AND** Magika returns text through its final output result
- **THEN** the system SHALL classify the upload as a plain text document

#### Scenario: Excel content is accepted
- **WHEN** the uploaded file name ends with `.xls` or `.xlsx`
- **AND** the upload MIME, Magika content label, or Magika MIME identifies the content as Excel
- **THEN** the system SHALL classify the upload as an Excel document

#### Scenario: CSV content is accepted
- **WHEN** the uploaded file name ends with `.csv`
- **AND** the upload MIME or Magika MIME identifies the content as text, CSV, or generic octet-stream content
- **THEN** the system SHALL classify the upload as a CSV document

#### Scenario: Unsupported file type is rejected before persistence
- **WHEN** the uploaded file does not match a supported file type
- **THEN** the system SHALL return HTTP 415 with `APIResponse.code` equal to `415`
- **AND** the response message SHALL be `unsupported file type`
- **AND** the system MUST NOT create a `knowledge_document` record

#### Scenario: File type detector fails before persistence
- **WHEN** Magika raises an unexpected runtime error while detecting the file type
- **THEN** the system SHALL return HTTP 500 with `APIResponse.code` equal to `500`
- **AND** the response message SHALL be `file type detection failed`
- **AND** the system MUST NOT create a `knowledge_document` record

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

### Requirement: Knowledge document lifecycle persistence
The system SHALL create a real `INIT` document before storage side effects and use explicit lifecycle states.

#### Scenario: Initial document row is persisted before storage side effects
- **WHEN** the system accepts a supported upload request
- **THEN** the system SHALL create and commit a `knowledge_document` record with status `INIT`
- **AND** the system SHALL use the generated `doc_id` for subsequent object storage paths

#### Scenario: Initial persistence failure fast fails
- **WHEN** the system cannot persist the initial `INIT` document record
- **THEN** the system SHALL return HTTP 500 with `APIResponse.code` equal to `500`
- **AND** the response message SHALL be `document persistence failed`
- **AND** the system MUST NOT upload the file to MinIO
- **AND** the system MUST NOT call MinerU

### Requirement: Document lifecycle concurrency control
The system SHALL protect document lifecycle updates with expected-state database updates instead of requiring a distributed lock for the first synchronous upload flow.

#### Scenario: Expected state transition succeeds
- **WHEN** the system transitions a document from `UPLOADED` to `CONVERTING`
- **AND** the current persisted status is `UPLOADED`
- **THEN** the system SHALL update the status to `CONVERTING`

#### Scenario: Unexpected state transition is rejected
- **WHEN** the system attempts to transition a document from `UPLOADED` to `CONVERTING`
- **AND** the current persisted status is not `UPLOADED`
- **THEN** the system SHALL return HTTP 409 with `APIResponse.code` equal to `409`
- **AND** the response message SHALL be `document state conflict`
- **AND** the system MUST NOT continue PDF conversion for that transition attempt

#### Scenario: Distributed lock service is not required
- **WHEN** the system processes a single synchronous upload request
- **THEN** the system SHALL NOT require Redis or another distributed lock service to guard that request

### Requirement: Original file storage
The system SHALL store each accepted original file in MinIO and save a stable full URL in the document record.

#### Scenario: Original file upload succeeds
- **WHEN** the system has committed an `INIT` document record
- **AND** the original file is uploaded to MinIO successfully
- **THEN** the system SHALL set `doc_url` to the full MinIO URL
- **AND** the system SHALL transition the document status to `UPLOADED`

#### Scenario: Original file upload fails
- **WHEN** the system has committed an `INIT` document record
- **AND** the original file upload to MinIO fails
- **THEN** the system SHALL return HTTP 502 with `APIResponse.code` equal to `502`
- **AND** the response message SHALL be `document storage failed`
- **AND** the document status SHALL remain `INIT`

#### Scenario: Object keys are generated from document identity
- **WHEN** the system stores document objects in MinIO
- **THEN** the system SHALL use object keys under `documents/{doc_id}/`
- **AND** the system MUST NOT trust raw user file names as path prefixes

### Requirement: Plain text conversion
The system SHALL treat supported Markdown and text files as already converted content.

#### Scenario: Plain text upload completes conversion
- **WHEN** a supported `.md`, `.markdown`, or `.txt` file has been uploaded to MinIO
- **THEN** the system SHALL set `converted_doc_url` equal to `doc_url`
- **AND** the system SHALL transition the document status to `CONVERTED`
- **AND** the system SHALL return HTTP 200 with the converted document metadata

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

### Requirement: PDF conversion with MinerU
The system SHALL convert uploaded PDF files to Markdown by calling MinerU and SHALL treat per-image processing as best-effort enrichment.

#### Scenario: Markdown image parsing uses bounded MinerU syntax
- **WHEN** the system parses Markdown image references during PDF conversion
- **THEN** the system SHALL recognize inline image references shaped as `![alt](target)` and `![](target)`
- **AND** local image targets SHALL be treated as MinerU-produced relative paths
- **AND** absolute image targets SHALL be treated as external URLs
- **AND** this change SHALL NOT require support for Markdown title syntax, angle-bracket destinations, escaped delimiters, nested parentheses, or user-uploaded Markdown sidecar image assets

#### Scenario: PDF upload enters converting state
- **WHEN** a PDF original file has been uploaded to MinIO
- **THEN** the system SHALL transition the document status from `UPLOADED` to `CONVERTING`
- **AND** the system SHALL call MinerU for PDF conversion

#### Scenario: MinerU ZIP is safely extracted
- **WHEN** MinerU returns a ZIP response
- **THEN** the system SHALL safely extract the ZIP to a temporary directory
- **AND** the system MUST reject unsafe ZIP entries whose resolved paths leave the temporary directory
- **AND** the system MUST reject duplicate normalized ZIP paths

#### Scenario: MinerU ZIP has no usable Markdown
- **WHEN** MinerU returns a ZIP response with no usable Markdown file
- **THEN** the system SHALL return HTTP 502 with `APIResponse.code` equal to `502`
- **AND** the response message SHALL be `document conversion failed`
- **AND** the document status SHALL be restored to or remain `UPLOADED`

#### Scenario: MinerU ZIP has multiple Markdown files
- **WHEN** MinerU returns a ZIP response with multiple Markdown files
- **THEN** the system SHALL select Markdown according to MinerU output conventions
- **AND** the system SHALL prefer a Markdown file whose normalized basename matches the uploaded PDF stem
- **AND** if no basename matches, the system SHALL prefer a Markdown file under a directory whose normalized name matches the PDF stem
- **AND** if no path matches the PDF stem, the system SHALL choose the lexicographically first normalized Markdown path
- **AND** the system MUST NOT fail solely because multiple Markdown files exist

#### Scenario: MinerU ZIP is invalid
- **WHEN** MinerU returns a corrupt ZIP, an unsafe ZIP entry, or duplicate normalized ZIP paths
- **THEN** the system SHALL return HTTP 502 with `APIResponse.code` equal to `502`
- **AND** the response message SHALL be `document conversion failed`
- **AND** the document status SHALL be restored to or remain `UPLOADED`

#### Scenario: PDF conversion uploads final Markdown
- **WHEN** MinerU returns a valid ZIP containing usable Markdown
- **THEN** the system SHALL upload the final Markdown under `documents/{doc_id}/converted/document.md`

#### Scenario: PDF conversion uploads available images
- **WHEN** MinerU returns a valid ZIP containing usable Markdown and images
- **THEN** the system SHALL attempt to upload extracted images under `documents/{doc_id}/assets/`
- **AND** failure to upload one extracted image MUST NOT fail the whole PDF conversion
- **AND** the system SHALL continue processing the remaining Markdown and images

#### Scenario: Markdown image reference is rewritten with generated description
- **WHEN** MinerU Markdown contains a relative image reference
- **AND** the referenced image is uploaded successfully
- **AND** image description generation succeeds with text whose `strip()` is non-empty
- **THEN** the system SHALL rewrite that image reference to the full MinIO URL
- **AND** the system SHALL set that image alt text to the generated image description

#### Scenario: Markdown image URL succeeds but description fails
- **WHEN** MinerU Markdown contains a relative image reference
- **AND** the referenced image is uploaded successfully
- **AND** image description generation fails or returns text whose `strip()` is empty
- **THEN** the system SHALL rewrite that image reference to the full MinIO URL
- **AND** the system SHALL set that image alt text to `图片解析错误`
- **AND** the document conversion MUST NOT fail because of that image description failure

#### Scenario: Markdown image URL cannot be rewritten
- **WHEN** MinerU Markdown contains a relative image reference
- **AND** the referenced image is missing, cannot be read, or cannot be uploaded
- **THEN** the system SHALL leave that image reference target unchanged
- **AND** the system SHALL set that image alt text to `图片解析错误`
- **AND** the document conversion MUST NOT fail because of that image processing failure

#### Scenario: Markdown image reference already uses absolute URL
- **WHEN** MinerU Markdown contains an image reference whose target is an absolute URL
- **THEN** the system SHALL leave that image target unchanged
- **AND** the system SHALL preserve the original image alt text unless local image description generation is available for that image
- **AND** the document conversion MUST NOT fetch arbitrary external image URLs for description generation

#### Scenario: PDF conversion completes successfully with image failures
- **WHEN** main Markdown selection and final converted Markdown upload succeed
- **AND** one or more images fail upload, URL rewrite, or description generation
- **THEN** the system SHALL set `converted_doc_url` to the final Markdown URL
- **AND** the system SHALL transition the document status to `CONVERTED`

#### Scenario: PDF conversion completes successfully
- **WHEN** PDF conversion and converted Markdown upload succeed
- **THEN** the system SHALL set `converted_doc_url` to the final Markdown URL
- **AND** the system SHALL transition the document status to `CONVERTED`
- **AND** the system SHALL return HTTP 200 with the converted document metadata

#### Scenario: PDF conversion failure leaves uploaded original
- **WHEN** MinerU request, ZIP extraction, Markdown selection, Markdown read, or converted object upload fails after original upload
- **THEN** the system SHALL return HTTP 502 with `APIResponse.code` equal to `502`
- **AND** the response message SHALL be `document conversion failed`
- **AND** the document status SHALL be restored to or remain `UPLOADED`
- **AND** the original `doc_url` SHALL remain available on the document record
- **AND** the system MUST NOT set `converted_doc_url`

#### Scenario: Conversion rollback failure is reported
- **WHEN** PDF conversion fails after the document has entered `CONVERTING`
- **AND** the system cannot restore the document status to `UPLOADED`
- **THEN** the system SHALL return HTTP 500 with `APIResponse.code` equal to `500`
- **AND** the response message SHALL be `document state rollback failed`

### Requirement: Processor extension boundary
The system SHALL route file handling through a processor factory so supported formats can use dedicated processors.

#### Scenario: Processor is selected by detected file type
- **WHEN** a supported file type is detected
- **THEN** the system SHALL select a concrete document processor for that type
- **AND** the upload service SHALL invoke that processor through a common processing interface

#### Scenario: Unsupported processor is absent
- **WHEN** no processor supports the detected file type
- **THEN** the system SHALL return HTTP 415 with `APIResponse.code` equal to `415`
- **AND** the response message SHALL be `unsupported file type`

### Requirement: Configuration and migration support
The system SHALL provide database migration, dependency, and environment configuration support for document upload.

#### Scenario: Environment example documents required configuration
- **WHEN** a developer opens `backend/.env.example`
- **THEN** it SHALL include `DATABASE_URL`, `MAX_UPLOAD_SIZE_MB`, `MINIO_*`, `MINERU_*`, and existing `OPENAI_*` variables

#### Scenario: File detection dependency is available
- **WHEN** backend dependencies are installed
- **THEN** the Magika Python package SHALL be available for document file type detection
