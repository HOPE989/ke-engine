## MODIFIED Requirements

### Requirement: PDF conversion with MinerU
The system SHALL convert uploaded PDF files to Markdown by calling MinerU and SHALL treat per-image processing as best-effort enrichment.

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
- **AND** image description generation succeeds with non-empty text
- **THEN** the system SHALL rewrite that image reference to the full MinIO URL
- **AND** the system SHALL set that image alt text to the generated image description

#### Scenario: Markdown image URL succeeds but description fails
- **WHEN** MinerU Markdown contains a relative image reference
- **AND** the referenced image is uploaded successfully
- **AND** image description generation fails or returns empty text
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
