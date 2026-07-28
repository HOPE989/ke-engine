## MODIFIED Requirements

### Requirement: Chat JSON extension containers
The system SHALL provide non-null JSONB containers for RAG references and message metadata, and SHALL persist a minimal document reference schema for grounded RAG answers.

#### Scenario: JSON containers receive defaults
- **WHEN** a message is inserted without `rag_references` or `metadata`
- **THEN** `rag_references` SHALL be persisted as an empty JSON array
- **AND** `metadata` SHALL be persisted as an empty JSON object

#### Scenario: Grounded references are persisted atomically
- **WHEN** a grounded ASSISTANT answer is committed with document evidence
- **THEN** each `rag_references` element SHALL contain `citationId`, `docId`, and `chunkId`
- **AND** it SHALL preserve available `fileName`, `url`, and `rerankScore`
- **AND** the complete answer and complete reference array SHALL commit in the same transaction

#### Scenario: ORM maps the reserved metadata column
- **WHEN** the SQLAlchemy Message model is inspected
- **THEN** its Python attribute SHALL be named `metadata_`
- **AND** the mapped PostgreSQL column SHALL remain named `metadata`

