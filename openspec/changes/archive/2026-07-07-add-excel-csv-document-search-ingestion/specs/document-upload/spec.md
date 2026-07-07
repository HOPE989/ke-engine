## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Spreadsheet origin conversion
The system SHALL treat supported Excel and CSV document-search uploads as already converted content by reusing the original object URL.

#### Scenario: Excel upload completes conversion by reusing origin
- **WHEN** a supported Excel file has been uploaded to MinIO
- **THEN** the Excel converter SHALL return the original `doc_url`
- **AND** the converter MUST NOT call MinerU
- **AND** the converter MUST NOT upload an intermediate converted Markdown or HTML object

#### Scenario: CSV upload completes conversion by reusing origin
- **WHEN** a supported CSV file has been uploaded to MinIO
- **THEN** the Excel converter SHALL return the original `doc_url`
- **AND** the converter MUST NOT call MinerU
- **AND** the converter MUST NOT upload an intermediate converted Markdown or HTML object
