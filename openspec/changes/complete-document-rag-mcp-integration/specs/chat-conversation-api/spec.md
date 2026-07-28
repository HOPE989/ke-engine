## ADDED Requirements

### Requirement: Message history exposes persisted RAG references
The current-user message history API SHALL return the persisted RAG reference array for every message.

#### Scenario: Grounded answer is listed
- **WHEN** the owner requests message history containing a grounded ASSISTANT answer
- **THEN** that message SHALL include its ordered `rag_references`
- **AND** each reference SHALL preserve `citationId`, `docId`, `chunkId`, and available source fields

#### Scenario: Message has no RAG evidence
- **WHEN** a USER message or non-RAG ASSISTANT message is listed
- **THEN** its `rag_references` SHALL be an empty array

