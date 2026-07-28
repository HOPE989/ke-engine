## ADDED Requirements

### Requirement: Grounded Answer uses the existing SSE protocol
The completion runtime SHALL stream grounded document answers through the existing application-owned SSE event types.

#### Scenario: Grounded model output is streamed
- **WHEN** the `grounded_answer` node emits model text
- **THEN** the adapter SHALL emit ordered `content_delta` events using the same projection rules as ordinary `llm` output
- **AND** it MUST NOT expose raw LangGraph or MCP events

#### Scenario: Empty-evidence answer is streamed
- **WHEN** `grounded_answer` returns the deterministic empty-evidence message
- **THEN** the adapter SHALL emit that message as `content_delta`
- **AND** the successful stream SHALL finish through the existing `completed` event

#### Scenario: MCP retrieval fails
- **WHEN** `knowledge_rag` fails before a complete grounded answer is produced
- **THEN** the completion SHALL emit the existing `error` terminal event
- **AND** it MUST NOT persist a partial ASSISTANT message or emit `completed`

### Requirement: Grounded completion persists references before completed
The completion runtime SHALL persist the final grounded answer and its RAG references before confirming success.

#### Scenario: Grounded Graph reaches END
- **WHEN** a document knowledge Graph run reaches `END`
- **THEN** the producer SHALL obtain the current run's `rag_references` from the final Chat state
- **AND** it SHALL persist the complete ASSISTANT content and those references in one transaction
- **AND** it SHALL emit `completed` only after that transaction commits

#### Scenario: Non-RAG completion succeeds
- **WHEN** a NON_BUSINESS, unsupported BUSINESS, clarification, or empty-evidence completion is persisted
- **THEN** the ASSISTANT message SHALL use an empty `rag_references` array unless the current Graph run produced non-empty document evidence

