## MODIFIED Requirements

### Requirement: Query Router has an explicit capability-scoped input
The system SHALL route one non-blank `standalone_query` only among the non-empty set of Retriever capabilities backed by nodes registered during RAG Graph assembly.

#### Scenario: Standalone query is routed
- **WHEN** Query Router is invoked after Query Rewrite
- **THEN** it SHALL use the resulting `standalone_query` as the information need
- **AND** it MUST NOT load conversation history, Chat persistence, checkpoints, Redis, or another caller-owned memory store

#### Scenario: Available capabilities come from registered nodes
- **WHEN** the RAG Graph is assembled
- **THEN** the Builder SHALL derive available `RetrieverKind` values from actual registered Retriever nodes
- **AND** it MUST NOT advertise a Retriever that has no executable node
- **AND** importing the RAG domain MUST NOT discover data sources or read process settings

#### Scenario: No capability is available
- **WHEN** no Retriever node is registered
- **THEN** the system SHALL fail during Graph assembly before invoking the Router model

### Requirement: Query Router extends the request-scoped RAG Graph
The system SHALL use the retrieval plan to transfer control to registered Retriever nodes in the request-scoped RAG Graph.

#### Scenario: Incremental document retrieval topology is compiled
- **WHEN** the RAG Graph Builder is inspected for this change
- **THEN** it SHALL contain `query_rewrite`, `query_router`, `document_hybrid`, and `collect_retrieval_outcomes`
- **AND** it SHALL connect selected `DOCUMENT_HYBRID` plans to `document_hybrid`
- **AND** it SHALL end after `collect_retrieval_outcomes`

#### Scenario: Router atomically updates and routes
- **WHEN** Query Router produces a valid plan
- **THEN** it SHALL update `retrieval_plan` and transfer control to every selected registered Retriever in one LangGraph routing result
- **AND** it MUST NOT route to `END` while a selected Retriever remains unexecuted

#### Scenario: Unimplemented Retriever nodes are absent
- **WHEN** only `DOCUMENT_HYBRID` is implemented
- **THEN** the production Graph SHALL advertise and register only `DOCUMENT_HYBRID`
- **AND** it MUST NOT register SQL or Graph placeholder nodes

#### Scenario: Graph remains request scoped and serializable
- **WHEN** the RAG Graph is compiled and invoked
- **THEN** it SHALL compile without a checkpointer
- **AND** its state MUST NOT contain a model client, callback handler, settings object, database connection, or external service client
