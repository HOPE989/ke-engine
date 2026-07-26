## ADDED Requirements

### Requirement: Query Router has an explicit capability-scoped input
The system SHALL route one non-blank `standalone_query` only among a non-empty set of Retriever capabilities supplied during RAG Graph assembly.

#### Scenario: Standalone query is routed
- **WHEN** Query Router is invoked after Query Rewrite
- **THEN** it SHALL use the resulting `standalone_query` as the information need
- **AND** it MUST NOT load conversation history, Chat persistence, checkpoints, Redis, or another caller-owned memory store

#### Scenario: Available capabilities are explicit
- **WHEN** the RAG Graph is assembled
- **THEN** the Builder SHALL bind a non-empty set of available `RetrieverKind` values to Query Router
- **AND** importing the RAG domain MUST NOT discover data sources or read process settings

#### Scenario: No capability is available
- **WHEN** the supplied available capability set is empty
- **THEN** the system SHALL fail before invoking the Router model

### Requirement: Query Router selects the minimum sufficient evidence sources
The system SHALL select one or more values from `DOCUMENT_HYBRID`, `SQL`, and `GRAPH` according to the evidence sources required to answer the standalone query.

#### Scenario: Document evidence is sufficient
- **WHEN** the query asks for rules, procedures, definitions, explanations, or other unstructured knowledge
- **THEN** Query Router SHALL select `DOCUMENT_HYBRID`
- **AND** it MUST NOT select another capability unless that capability supplies independently required evidence

#### Scenario: Structured data evidence is sufficient
- **WHEN** the query asks for exact business records, status, filtering, counts, aggregates, or comparisons available as structured data
- **THEN** Query Router SHALL select `SQL`

#### Scenario: Graph evidence is sufficient
- **WHEN** the query asks for topology, paths, reachability, dependencies, or modeled entity relationships
- **THEN** Query Router SHALL select `GRAPH`

#### Scenario: Multiple evidence sources are required
- **WHEN** independent parts of the query require different evidence source types
- **THEN** Query Router SHALL select the minimum sufficient set containing each required Retriever kind
- **AND** the output order MUST NOT represent execution priority

#### Scenario: Keyword alone is insufficient
- **WHEN** a word such as “多少” or “关系” appears but the authoritative evidence source is a document rather than structured data or a modeled graph
- **THEN** Query Router SHALL route according to the evidence source
- **AND** it MUST NOT route solely from the surface keyword

### Requirement: Query Router produces validated structured output
The system SHALL validate the model response as a `QueryRouteResult` and normalize it into a serializable `RetrievalPlan`.

#### Scenario: Valid structured output succeeds
- **WHEN** the model returns one or more known Retriever kinds that are all available
- **THEN** the plan SHALL contain those selected Retrievers
- **AND** `decision_source` SHALL be `MODEL`

#### Scenario: Duplicate valid values are normalized
- **WHEN** the model returns the same valid Retriever kind more than once
- **THEN** the system SHALL retain that Retriever exactly once
- **AND** it SHALL order selected Retrievers canonically as `DOCUMENT_HYBRID`, `SQL`, then `GRAPH`

#### Scenario: Routing reason is informational
- **WHEN** the model returns a routing decision
- **THEN** `routing_reason` SHALL be a non-blank concise explanation of the required evidence source types
- **AND** it MUST NOT control authorization, capability availability, or Graph execution

#### Scenario: Unsupported execution details are absent
- **WHEN** a `QueryRouteResult` or `RetrievalPlan` is produced
- **THEN** it MUST NOT contain SQL, Cypher, per-Retriever query strings, connection parameters, a confidence score, or a caller-provided route override

### Requirement: Query Router enforces available capabilities server-side
The system SHALL treat model output as untrusted and SHALL NOT accept a selected Retriever outside the assembly-supplied available capability set.

#### Scenario: Model selects an unavailable capability
- **WHEN** any selected Retriever is not included in the available capability set
- **THEN** the complete model decision SHALL be invalid
- **AND** the system MUST NOT silently keep and execute only the remaining values

#### Scenario: Router does not grant authorization
- **WHEN** Query Router selects a capability
- **THEN** that decision MUST NOT grant access to a tenant, knowledge base, table, field, graph, or other protected resource

### Requirement: Query Router has deterministic fallback behavior
The system SHALL perform no Router retry and SHALL use `DOCUMENT_HYBRID` as the only automatic fallback capability when it is available.

#### Scenario: Model invocation fails
- **WHEN** the Router model raises an ordinary exception or times out
- **THEN** the node SHALL produce a plan selecting only `DOCUMENT_HYBRID` when that capability is available
- **AND** `decision_source` SHALL be `FALLBACK`
- **AND** the node MUST NOT retry the model

#### Scenario: Model output is invalid
- **WHEN** the response is empty, malformed, selects no Retriever, contains an unknown value, or selects an unavailable capability
- **THEN** the node SHALL produce a plan selecting only `DOCUMENT_HYBRID` when that capability is available

#### Scenario: Safe fallback is unavailable
- **WHEN** Router fallback is required and `DOCUMENT_HYBRID` is not available
- **THEN** the node SHALL raise a stable Router-unavailable error
- **AND** it MUST NOT default to `SQL`, `GRAPH`, or all capabilities

#### Scenario: Cancellation is not converted to fallback
- **WHEN** Graph execution is cancelled by the runtime
- **THEN** Query Router MUST NOT convert cancellation into a successful fallback plan

### Requirement: Query Router extends the request-scoped RAG Graph
The system SHALL extend the pipeline-level RAG Graph to the incremental topology `START -> query_rewrite -> query_router -> END`.

#### Scenario: Incremental Router topology is compiled
- **WHEN** the RAG Graph Builder is inspected for this change
- **THEN** it SHALL contain exactly the `query_rewrite` and `query_router` business nodes
- **AND** it SHALL connect them using only the fixed edges in the incremental topology

#### Scenario: Router only updates state
- **WHEN** Query Router completes in this change
- **THEN** it SHALL add the `retrieval_plan` to `RagState`
- **AND** it MUST NOT execute a Retriever or return a dynamic `goto`

#### Scenario: Graph remains request scoped and serializable
- **WHEN** the RAG Graph is compiled and invoked
- **THEN** it SHALL compile without a checkpointer
- **AND** its state MUST NOT contain a model client, callback handler, settings object, database connection, or external service client

### Requirement: Query Router preserves callback observability
The system SHALL pass caller-provided LangChain callbacks through the Graph and Router model invocation without making observability a business dependency.

#### Scenario: Callback is supplied
- **WHEN** a caller invokes the RAG Graph with a callback
- **THEN** the Query Router model call and resulting retrieval plan SHALL be observable beneath that callback

#### Scenario: Callback is absent
- **WHEN** a caller invokes the Graph without Langfuse resources
- **THEN** Query Router behavior and output SHALL remain unchanged

### Requirement: Query Router has offline tests and explicit live-model evaluation
The system SHALL provide deterministic default tests and a separate opt-in path for evaluating Router quality with a configured live model.

#### Scenario: Default tests are offline
- **WHEN** the default backend test suite runs
- **THEN** Query Router tests SHALL use fake or stub Chat models
- **AND** they MUST NOT require network access, provider credentials, Langfuse, Redis, PostgreSQL, Elasticsearch, Neo4j, or MCP

#### Scenario: Fixtures cover routing classes
- **WHEN** repository Router cases are inspected
- **THEN** they SHALL include every single Retriever, each two-Retriever combination, all three Retrievers, capability-restricted inputs, and fallback cases

#### Scenario: Route set is scored objectively
- **WHEN** a code evaluator scores a Router result
- **THEN** it SHALL compare selected Retriever sets independently of order
- **AND** it MAY report exact-set accuracy, per-Retriever precision and recall, over-routing, and under-routing
- **AND** it MUST NOT score `routing_reason` using exact wording or keyword overlap

#### Scenario: Live evaluation is explicit
- **WHEN** a developer runs the live-model Router evaluation with valid model configuration
- **THEN** it SHALL invoke the production RAG Graph against the Router Dataset
- **AND** default pytest or CI MUST NOT run that evaluation implicitly

