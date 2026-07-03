## MODIFIED Requirements

### Requirement: Segment metadata payload
The system SHALL store self-contained metadata on each segment, including document fields, splitter metadata, and image references found in the segment text.

#### Scenario: Segment metadata includes document and chunk fields
- **WHEN** the system persists a segment
- **THEN** segment `metadata` SHALL include `skipEmbedding`
- **AND** segment `metadata` SHALL include `chunkId`
- **AND** segment `metadata` SHALL include `docId`
- **AND** segment `metadata` SHALL include `fileName`
- **AND** segment `metadata` SHALL include `url`
- **AND** segment `metadata` SHALL include `accessibleBy`
- **AND** segment `metadata` SHALL include `parentChunkId`
- **AND** segment `metadata` SHALL include `langchain`
- **AND** segment `metadata` SHALL include `images`

#### Scenario: Metadata duplicates selected database fields
- **WHEN** the system persists a segment
- **THEN** `metadata.skipEmbedding` SHALL equal the segment `skip_embedding` column
- **AND** `metadata.chunkId` SHALL equal the segment `chunk_id` column
- **AND** `metadata.docId` SHALL equal the segment `document_id` column serialized as a string

#### Scenario: Metadata inherits document fields
- **WHEN** the system persists a segment
- **THEN** `metadata.fileName` SHALL equal the source document `doc_title`
- **AND** `metadata.url` SHALL equal the source document `converted_doc_url`
- **AND** `metadata.accessibleBy` SHALL equal the source document `accessible_by`

#### Scenario: LangChain metadata is namespaced
- **WHEN** the LangChain splitter produces metadata for a segment
- **THEN** the system SHALL store that metadata under `metadata.langchain`
- **AND** the system MUST NOT flatten LangChain metadata into the top-level segment metadata payload

#### Scenario: Segment image metadata is extracted from chunk Markdown
- **WHEN** the system persists a segment whose chunk text contains supported Markdown image references
- **THEN** `metadata.images` SHALL contain one entry per supported Markdown image reference found in that segment text
- **AND** each image entry SHALL include `url` equal to the Markdown image target
- **AND** each image entry SHALL include `alt` equal to the Markdown image alt text
- **AND** each image entry SHALL include `source` equal to `markdown-image`

#### Scenario: Segment without images records empty image metadata
- **WHEN** the system persists a segment whose chunk text contains no supported Markdown image references
- **THEN** `metadata.images` SHALL be an empty list

#### Scenario: Stored document image object key is derived when possible
- **WHEN** a segment image URL belongs to the configured document object storage base URL and bucket
- **THEN** that image metadata entry SHALL include `objectKey` equal to the storage object key
- **AND** `objectKey` SHALL be under `documents/{doc_id}/`

#### Scenario: External image URLs remain metadata URLs only
- **WHEN** a segment image URL does not belong to the configured document object storage base URL and bucket
- **THEN** that image metadata entry SHALL include the original `url`
- **AND** the system SHALL NOT derive an `objectKey` for that external URL
