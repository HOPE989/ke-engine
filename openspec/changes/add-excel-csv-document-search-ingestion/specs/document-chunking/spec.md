## MODIFIED Requirements

### Requirement: Converted Markdown retrieval
The system SHALL resolve `knowledge_document.converted_doc_url` to a validated MinIO object key before Markdown-backed splitters download and decode Markdown content.

#### Scenario: Markdown converted URL is resolved to object key
- **WHEN** a client requests chunking for a `CONVERTED` Markdown-backed document with `converted_doc_url`
- **THEN** the selected Markdown splitter SHALL parse `converted_doc_url` using the configured storage `public_base_url` and `bucket`
- **AND** it SHALL extract the object key from the URL path after the bucket segment
- **AND** it SHALL download bytes through `DocumentObjectStorage.download_bytes(object_key=...)`
- **AND** it SHALL decode the downloaded bytes as UTF-8

#### Scenario: Converted URL outside configured storage is rejected
- **WHEN** `converted_doc_url` does not belong to the configured storage `public_base_url` or `bucket`
- **THEN** the system SHALL return HTTP 409 with `APIResponse.code` equal to `409`
- **AND** the response message SHALL be `document state conflict`
- **AND** the system MUST NOT create `knowledge_segment` records

#### Scenario: Converted URL path cannot produce object key
- **WHEN** `converted_doc_url` belongs to the configured storage base but its path cannot be parsed into a non-empty object key after the bucket segment
- **THEN** the system SHALL return HTTP 409 with `APIResponse.code` equal to `409`
- **AND** the response message SHALL be `document state conflict`
- **AND** the system MUST NOT create `knowledge_segment` records

#### Scenario: Converted Markdown download fails
- **WHEN** the converted Markdown object does not exist
- **OR** object storage returns a download error
- **THEN** the system SHALL return HTTP 502 with `APIResponse.code` equal to `502`
- **AND** the response message SHALL be `converted markdown unavailable`
- **AND** the system MUST NOT create `knowledge_segment` records

#### Scenario: Converted Markdown is not UTF-8
- **WHEN** the converted Markdown bytes cannot be decoded as UTF-8
- **THEN** the system SHALL return HTTP 422 with `APIResponse.code` equal to `422`
- **AND** the response message SHALL be `converted markdown invalid`
- **AND** the system MUST NOT create `knowledge_segment` records

## ADDED Requirements

### Requirement: Type-specific document splitting
The system SHALL select a file-type-specific splitter before loading converted document content.

#### Scenario: Workflow delegates loading and splitting to selected splitter
- **WHEN** a converted document is ready for chunking
- **THEN** the workflow SHALL select a splitter through `DocumentSplitterFactory` using `knowledge_document.file_type`
- **AND** it SHALL pass the document, storage adapter, and chunk ID generator to the selected splitter
- **AND** it SHALL NOT pre-load all documents as UTF-8 Markdown before selecting the splitter

### Requirement: Excel2HTML spreadsheet chunk splitting
The system SHALL split Excel and CSV document-search files into RAGFlow-like compact HTML table sections before applying the existing parent-child length rule.

#### Scenario: Spreadsheet section shape
- **WHEN** the Excel2HTML splitter creates a section
- **THEN** the section text SHALL be a compact string shaped as `<table><caption>{file_name} - {sheet_name}</caption>{header_tr}{data_tr...}</table>\n`
- **AND** `header_tr` SHALL use `<tr><th>...</th></tr>` cells from the first row
- **AND** `data_tr` SHALL use `<tr><td>...</td></tr>` cells from data rows
- **AND** all caption and cell values SHALL be HTML-escaped after converting `None` to empty string and stripping non-empty values

#### Scenario: Spreadsheet sections use fixed 12 data rows
- **WHEN** a sheet has data rows after the first header row
- **THEN** the Excel2HTML splitter SHALL create one section per group of up to 12 data rows
- **AND** every section SHALL repeat the first row as `header_tr`
- **AND** the 12-row value MUST NOT be configurable through runtime settings or the chunk request

#### Scenario: Spreadsheet section within chunk size creates normal segment
- **WHEN** an Excel2HTML section has non-empty text
- **AND** the section text length is less than or equal to `chunk_size`
- **THEN** the system SHALL persist one segment for that section
- **AND** the segment SHALL have `skip_embedding` set to `false`
- **AND** the segment metadata SHALL have `parentChunkId` set to `null`

#### Scenario: Spreadsheet section exceeding chunk size creates parent and child segments
- **WHEN** an Excel2HTML section has text length greater than `chunk_size`
- **THEN** the system SHALL persist one parent segment containing the complete HTML section
- **AND** the parent segment SHALL have `skip_embedding` set to `true`
- **AND** the system SHALL recursively split that parent text into child segments
- **AND** each child segment SHALL have `skip_embedding` set to `false`
- **AND** each child segment metadata SHALL have `parentChunkId` equal to the parent segment `chunkId`
- **AND** each child segment SHALL inherit the parent section metadata under `metadata.langchain`

#### Scenario: Empty and header-only sheets produce no section
- **WHEN** an Excel sheet or CSV input has no rows
- **OR** it has only the first header row and no data rows
- **THEN** the Excel2HTML splitter SHALL NOT persist a segment for that sheet or input

#### Scenario: Spreadsheet metadata records section origin
- **WHEN** the system persists an Excel2HTML segment
- **THEN** `metadata.langchain` SHALL include `sourceFormat`, `sheetName`, `headerRow`, `dataStartRow`, `dataEndRow`, `chunkRows`, and `htmlTableIndex`
- **AND** CSV input SHALL use `sheetName` equal to `Data`
