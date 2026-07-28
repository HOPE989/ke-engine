## ADDED Requirements

### Requirement: RAG is exposed as one internal MCP Tool
The system SHALL expose the existing document RAG pipeline through one internal MCP Streamable HTTP Tool named `retrieve_evidence`.

#### Scenario: MCP Tool is discovered
- **WHEN** an MCP Client initializes a session and lists Tools
- **THEN** the server SHALL advertise `retrieve_evidence`
- **AND** it MUST NOT advertise SQL, GraphDB, expert-retrieval, health-check, or answer-generation Tools

#### Scenario: Tool is called without authentication
- **WHEN** an internal client calls `retrieve_evidence`
- **THEN** the server SHALL accept the request without OAuth, access-token, tenant, role, or user authentication
- **AND** it SHALL treat the provided document scope as trusted internal request data

### Requirement: Retrieve evidence has a minimal validated request
The `retrieve_evidence` Tool SHALL accept one non-blank standalone query and a document retrieval scope.

#### Scenario: Valid document request is accepted
- **WHEN** the request contains a non-blank `query` and at least one non-blank `accessibleBy` value
- **THEN** the application SHALL construct a RAG Graph input using that query and immutable request-level scope
- **AND** it SHALL include optional `docIds` when supplied

#### Scenario: Chat-owned context is rejected
- **WHEN** the request contains conversation context or business intent
- **THEN** validation SHALL reject those fields
- **AND** RAG MUST NOT load Chat history or classify a business Intent

#### Scenario: Invalid request is rejected before retrieval
- **WHEN** `query` is blank or `accessibleBy` is absent, empty, or malformed
- **THEN** the Tool call SHALL fail validation
- **AND** the system MUST NOT invoke the RAG Graph or Elasticsearch

### Requirement: The MCP service invokes the existing RAG Graph
The RAG MCP application service SHALL execute the compiled, checkpointer-free RAG Graph and SHALL NOT reimplement Query Rewrite or document retrieval in the Tool adapter.

#### Scenario: Evidence retrieval executes
- **WHEN** a valid `retrieve_evidence` request is called
- **THEN** the application service SHALL invoke the Graph with `standalone_query` and `document_retrieval_scope`
- **AND** the Graph SHALL execute Query Router, Hybrid Document Retrieval, and outcome collection
- **AND** it MUST NOT execute conversation-dependent Query Rewrite

#### Scenario: MCP adapter remains transport-only
- **WHEN** the MCP server module is inspected
- **THEN** it SHALL delegate retrieval to a plain Python application service
- **AND** `domains.rag` MUST NOT import MCP SDK server, session, Tool, or transport types

### Requirement: RAG returns a minimal document EvidencePackage
The system SHALL project a completed document retrieval outcome into an EvidencePackage containing `query`, `selectedRetrievers`, and ordered `evidenceItems`.

#### Scenario: Successful candidates become evidence
- **WHEN** `DOCUMENT_HYBRID` returns `SUCCESS`
- **THEN** each retained candidate SHALL produce one evidence item containing `citationId`, `sourceType=DOCUMENT`, `content`, `docId`, and `chunkId`
- **AND** it SHALL preserve available `fileName`, `url`, and `rerankScore`
- **AND** `citationId` SHALL equal `<docId>:<chunkId>`
- **AND** evidence item order SHALL equal the final reranked candidate order
- **AND** `selectedRetrievers` SHALL contain `DOCUMENT_HYBRID`

#### Scenario: Empty retrieval returns an empty package
- **WHEN** `DOCUMENT_HYBRID` returns `EMPTY`
- **THEN** the Tool call SHALL succeed with an EvidencePackage whose `evidenceItems` is an empty array

#### Scenario: Failed retrieval fails the Tool call
- **WHEN** `DOCUMENT_HYBRID` returns `FAILED` or the Graph invocation raises
- **THEN** the application service SHALL fail the Tool call
- **AND** it MUST NOT return an empty EvidencePackage that disguises the execution failure

#### Scenario: Internal diagnostics remain internal
- **WHEN** an EvidencePackage is serialized for MCP
- **THEN** it MUST NOT include raw Graph state, retrieval plan, provider response, exception text, credentials, Elasticsearch clients, callback handlers, or complete stage diagnostics

### Requirement: RAG MCP reuses existing resources with minimal configuration
The RAG MCP entrypoint SHALL reuse the existing model and retrieval infrastructure and SHALL require no new RAG-specific provider configuration.

#### Scenario: Service starts for local demonstration
- **WHEN** the developer starts the RAG MCP entrypoint with the existing project configuration
- **THEN** it SHALL assemble the Chat Model, Embedding Model, Elasticsearch retrieval store, Qwen3 Reranker, parent chunk cache, and optional Langfuse callback
- **AND** it SHALL serve Streamable HTTP on the fixed local development host and port

#### Scenario: No production service features are introduced
- **WHEN** the change configuration and service routes are inspected
- **THEN** the system MUST NOT add health, readiness, or liveness endpoints
- **AND** it MUST NOT add settings for authentication, retries, circuit breaking, rate limiting, Tool visibility, retrieval thresholds, or cross-service trace propagation
