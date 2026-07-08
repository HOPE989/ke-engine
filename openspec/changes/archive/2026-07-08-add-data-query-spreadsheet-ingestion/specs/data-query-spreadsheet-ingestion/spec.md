## ADDED Requirements

### Requirement: DATA_QUERY spreadsheet ingestion eligibility
The system SHALL run relational spreadsheet ingestion only for uploaded documents whose `knowledge_base_type` is `DATA_QUERY` and whose detected file type is Excel or CSV.

#### Scenario: DATA_QUERY Excel enters relational ingestion
- **WHEN** the conversion worker processes an `UPLOADED` document with `knowledge_base_type` equal to `DATA_QUERY`
- **AND** the document file type is `excel`
- **THEN** the worker SHALL process the original file through the DATA_QUERY relational ingestion workflow
- **AND** the worker MUST NOT run DOCUMENT_SEARCH Excel origin conversion for that document

#### Scenario: DATA_QUERY CSV enters relational ingestion
- **WHEN** the conversion worker processes an `UPLOADED` document with `knowledge_base_type` equal to `DATA_QUERY`
- **AND** the document file type is `csv`
- **THEN** the worker SHALL process the original file through the DATA_QUERY relational ingestion workflow
- **AND** the worker MUST NOT run DOCUMENT_SEARCH CSV origin conversion for that document

#### Scenario: DOCUMENT_SEARCH spreadsheet behavior is excluded
- **WHEN** a document has `knowledge_base_type` equal to `DOCUMENT_SEARCH`
- **AND** the document file type is `excel` or `csv`
- **THEN** the DATA_QUERY relational ingestion workflow MUST NOT process that document

### Requirement: DATA_QUERY table metadata schema
The system SHALL persist one `table_meta` record for each DATA_QUERY spreadsheet physical table.

#### Scenario: Table metadata table exists after migration
- **WHEN** Alembic migrations are applied
- **THEN** the database SHALL contain a `table_meta` table

#### Scenario: Table metadata columns are defined
- **WHEN** the `table_meta` table is inspected
- **THEN** `id` SHALL be a primary key
- **AND** `namespace` SHALL be a non-null string identifying the uploader namespace
- **AND** `document_id` SHALL be a non-null foreign key to `knowledge_document.doc_id`
- **AND** `table_name` SHALL be the non-null user-provided logical table name
- **AND** `description` SHALL store the DATA_QUERY table description
- **AND** `create_sql` SHALL store the generated PostgreSQL DDL after successful ingestion
- **AND** `columns_info` SHALL store a PostgreSQL `JSONB` payload describing the generated physical table and columns after successful ingestion
- **AND** `created_at` SHALL be a timezone-aware timestamp with a current-time default
- **AND** `updated_at` SHALL be a timezone-aware timestamp with a current-time default

#### Scenario: Table metadata uniqueness is enforced
- **WHEN** migrations are applied
- **THEN** `table_meta` SHALL enforce uniqueness for `(namespace, table_name)`
- **AND** `table_meta` SHALL enforce uniqueness for `document_id`

#### Scenario: Table metadata describes one generated table
- **WHEN** DATA_QUERY spreadsheet ingestion succeeds
- **THEN** `columns_info` SHALL include `originalSheetName`
- **AND** `columns_info` SHALL include `physicalTableName`
- **AND** `columns_info` SHALL include `columns`
- **AND** each column entry SHALL include `ordinal`, `header`, `columnName`, and `type`
- **AND** `columns_info` MUST NOT require a top-level `sheets` array

### Requirement: DATA_QUERY single-table spreadsheet parsing
The system SHALL parse DATA_QUERY Excel and CSV files into exactly one table-shaped dataset before creating the generated database table.

#### Scenario: Excel with one data sheet is accepted
- **WHEN** a DATA_QUERY Excel workbook contains exactly one non-empty worksheet with a header row and at least one data row
- **THEN** the system SHALL ingest that worksheet as the DATA_QUERY table
- **AND** `columns_info.originalSheetName` SHALL equal the original worksheet name

#### Scenario: Excel with only empty sheets is rejected
- **WHEN** a DATA_QUERY Excel workbook has no worksheet with both a header row and at least one data row
- **THEN** ingestion SHALL fail
- **AND** the document SHALL remain `UPLOADED`
- **AND** no generated physical table SHALL be committed

#### Scenario: Excel with multiple data sheets is rejected
- **WHEN** a DATA_QUERY Excel workbook contains more than one worksheet with data rows
- **THEN** ingestion SHALL fail
- **AND** the document SHALL remain `UPLOADED`
- **AND** no generated physical table SHALL be committed

#### Scenario: Excel header-only non-empty sheet is rejected
- **WHEN** a DATA_QUERY Excel workbook contains a non-empty worksheet with only a header row and no data rows
- **THEN** ingestion SHALL fail
- **AND** the document SHALL remain `UPLOADED`
- **AND** no generated physical table SHALL be committed

#### Scenario: Empty extra Excel sheets are ignored
- **WHEN** a DATA_QUERY Excel workbook contains one worksheet with data rows
- **AND** all other worksheets are fully empty
- **THEN** the system SHALL ingest the worksheet with data rows
- **AND** fully empty worksheets SHALL NOT affect the generated table metadata

#### Scenario: CSV is parsed as one table
- **WHEN** a DATA_QUERY CSV file is ingested
- **THEN** the system SHALL treat it as one table-shaped dataset
- **AND** `columns_info.originalSheetName` SHALL be `Data`

#### Scenario: CSV without data rows is rejected
- **WHEN** a DATA_QUERY CSV file contains no rows
- **OR** a DATA_QUERY CSV file contains only a header row and no data rows
- **THEN** ingestion SHALL fail
- **AND** the document SHALL remain `UPLOADED`
- **AND** no generated physical table SHALL be committed

### Requirement: DATA_QUERY physical table and column generation
The system SHALL generate PostgreSQL-safe physical table names and column names for DATA_QUERY spreadsheet ingestion.

#### Scenario: Physical table name is generated
- **WHEN** a DATA_QUERY spreadsheet is ingested
- **THEN** its physical table name SHALL be generated from a fixed DATA_QUERY prefix, the uploader namespace token, and the logical `tableName`
- **AND** the physical table name MUST NOT include the original Excel sheet name
- **AND** the physical table name MUST NOT include raw unbounded uploader text

#### Scenario: Physical column names are generated
- **WHEN** a DATA_QUERY spreadsheet has `N` header cells
- **THEN** the generated physical table SHALL contain `N` data columns named `col_001`, `col_002`, and so on in header order
- **AND** the original header text SHALL be preserved in `columns_info`

#### Scenario: Data columns use text type
- **WHEN** a DATA_QUERY physical table is created
- **THEN** every generated spreadsheet data column SHALL use PostgreSQL `TEXT`
- **AND** the system SHALL NOT infer numeric, date, boolean, or JSON column types in this change

#### Scenario: Dynamic identifiers are generated or validated
- **WHEN** the system composes dynamic DDL or DML for DATA_QUERY ingestion
- **THEN** every table and column identifier SHALL be generated by the backend from validated tokens
- **AND** row values SHALL be bound as query parameters rather than interpolated into SQL strings

### Requirement: DATA_QUERY transactional import
The system SHALL create the DATA_QUERY physical table, row data, metadata, and document terminal state in one database transaction.

#### Scenario: Successful import commits table metadata and document state together
- **WHEN** DATA_QUERY spreadsheet parsing succeeds for the owning document
- **AND** the generated physical table does not already exist
- **THEN** the system SHALL create the generated physical table
- **AND** the system SHALL insert all parsed data rows
- **AND** the system SHALL update `table_meta.create_sql` and `table_meta.columns_info`
- **AND** the system SHALL update the document status from `UPLOADED` to `STORED`
- **AND** all of those database changes SHALL commit in one transaction

#### Scenario: Import failure rolls back all database changes
- **WHEN** DATA_QUERY table creation, data insertion, metadata update, or document status update fails
- **THEN** the database transaction SHALL roll back
- **AND** the document SHALL remain `UPLOADED`
- **AND** partial generated physical tables or partial metadata updates MUST NOT be committed

#### Scenario: Different document cannot import existing reservation
- **WHEN** the worker processes a DATA_QUERY document
- **AND** the matching `table_meta` record belongs to a different `document_id`
- **THEN** ingestion SHALL fail before creating a physical table
- **AND** the current document SHALL remain `UPLOADED`

#### Scenario: Existing physical table is not automatically dropped
- **WHEN** the worker processes an `UPLOADED` DATA_QUERY document
- **AND** the generated physical table already exists
- **THEN** ingestion SHALL fail before inserting data
- **AND** the worker MUST NOT drop or rebuild the existing physical table
- **AND** the document SHALL remain `UPLOADED`

### Requirement: DATA_QUERY worker idempotency and locking
The system SHALL use the per-document conversion lock and document state to make DATA_QUERY worker processing idempotent.

#### Scenario: Document conversion lock is acquired before import
- **WHEN** the worker starts DATA_QUERY spreadsheet ingestion
- **THEN** it SHALL hold the document conversion lock for `document:{doc_id}:convert`
- **AND** it SHALL release the lock after the ingestion attempt finishes

#### Scenario: Busy document conversion lock is retryable
- **WHEN** another worker already holds the document conversion lock for the same `doc_id`
- **THEN** the worker SHALL NOT parse the file
- **AND** the worker SHALL NOT open the DATA_QUERY import transaction
- **AND** the worker SHALL leave the consumed Kafka message uncommitted so delivery can be retried

#### Scenario: Already stored DATA_QUERY document is idempotent
- **WHEN** the worker receives a conversion message for a DATA_QUERY spreadsheet document whose status is already `STORED`
- **THEN** it SHALL treat the message as already complete
- **AND** it SHALL NOT drop or recreate the physical table
- **AND** it SHALL commit the consumed Kafka message

#### Scenario: Non-uploaded DATA_QUERY document is terminal for this worker
- **WHEN** the worker receives a conversion message for a DATA_QUERY spreadsheet document whose status is neither `UPLOADED` nor `STORED`
- **THEN** it SHALL NOT create a physical table
- **AND** it SHALL treat the message as terminal for this worker

### Requirement: DATA_QUERY document lifecycle boundary
The system SHALL use `STORED` as the successful terminal document state for DATA_QUERY spreadsheet ingestion.

#### Scenario: Successful DATA_QUERY import marks document stored
- **WHEN** DATA_QUERY spreadsheet ingestion commits successfully
- **THEN** the document status SHALL be `STORED`
- **AND** `knowledge_document.converted_doc_url` SHALL remain `NULL`

#### Scenario: DATA_QUERY import does not enter document search stages
- **WHEN** a DATA_QUERY spreadsheet document reaches `STORED`
- **THEN** the system SHALL NOT create `knowledge_segment` rows for that document
- **AND** the system SHALL NOT dispatch vector storage for that document
- **AND** the document MUST NOT pass through `CONVERTED`, `CHUNKED`, or `VECTOR_STORED` as part of this ingestion path
