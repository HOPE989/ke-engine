## MODIFIED Requirements

### Requirement: Query Rewrite is the first stage of the RAG Graph
The system SHALL keep Query Rewrite as the first business stage of the request-scoped, pipeline-level RAG Graph, whose current topology is `START -> query_rewrite -> query_router -> END`.

#### Scenario: Incremental RAG topology is compiled
- **WHEN** the RAG Graph builder is inspected or tested for this increment
- **THEN** it SHALL contain the business nodes named `query_rewrite` and `query_router`
- **AND** it SHALL connect `START` to `query_rewrite`, `query_rewrite` to `query_router`, and `query_router` to `END`
- **AND** its top-level state and builder SHALL represent the RAG pipeline rather than a stage-specific subgraph

#### Scenario: Graph is request scoped
- **WHEN** the RAG Graph is compiled
- **THEN** it SHALL compile without a checkpointer
- **AND** it MUST NOT create conversation memory or cross-request state

#### Scenario: Model is injected
- **WHEN** the Query Rewrite node executes
- **THEN** the RAG Graph builder SHALL have bound one explicitly provided Chat model to the node during assembly
- **AND** the Graph MUST NOT define a runtime context solely for model injection
- **AND** importing the RAG domain MUST NOT create a model client or read process settings

#### Scenario: Graph state remains serializable
- **WHEN** the RAG Graph state after Query Rewrite is inspected
- **THEN** it SHALL contain only request data and serializable RAG stage outputs
- **AND** it MUST NOT contain a model client, Langfuse client, callback handler, settings object, database connection, or external service client
