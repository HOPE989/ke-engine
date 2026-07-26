## Purpose

Define scoped hybrid document retrieval that combines Elasticsearch BM25 and KNN results with application-level reciprocal rank fusion.

## Requirements

### Requirement: Hybrid document retrieval has a scoped request contract
The system SHALL retrieve documents using one non-blank `standalone_query` and a server-provided document retrieval scope.

#### Scenario: Access scope is present
- **WHEN** `DOCUMENT_HYBRID` executes
- **THEN** the request SHALL contain at least one non-blank authorized `accessibleBy` value
- **AND** it MAY contain a server-provided set of allowed `docId` values

#### Scenario: Scope is missing or invalid
- **WHEN** the document retrieval scope is missing, empty, malformed, or caller-controlled without server validation
- **THEN** the system SHALL fail before creating the Retriever or querying Elasticsearch
- **AND** it MUST NOT perform an unfiltered search

#### Scenario: Scope is bound per request
- **WHEN** the Graph prepares `DOCUMENT_HYBRID` for one request
- **THEN** it SHALL create a request-scoped Retriever with immutable search filters
- **AND** it MUST NOT mutate filters on a process-wide Retriever shared by concurrent requests

### Requirement: Hybrid document retrieval uses a custom LangChain Retriever
The system SHALL implement `DOCUMENT_HYBRID` as a custom LangChain `BaseRetriever` that reuses the existing Elasticsearch client, `ElasticsearchStore`, and Embedding Model.

#### Scenario: Vector store is configured
- **WHEN** the retrieval Elasticsearch store is assembled
- **THEN** it SHALL use `DenseVectorStrategy` with `hybrid=False`
- **AND** it MUST NOT generate an Elasticsearch native RRF retriever

#### Scenario: Request-scoped Retriever is created
- **WHEN** `document_hybrid` has a validated request
- **THEN** the factory SHALL create a request-scoped custom `BaseRetriever`
- **AND** it SHALL bind immutable scope, result limit, candidate limit, and `rank_constant=60`

#### Scenario: Asynchronous invocation uses the standard contract
- **WHEN** `document_hybrid` executes the Retriever
- **THEN** it SHALL call `ainvoke` with the standalone query and Runnable config
- **AND** the Retriever SHALL return a fused list of LangChain `Document` values

#### Scenario: Existing infrastructure is reused
- **WHEN** the custom Retriever is assembled
- **THEN** it SHALL reuse the configured Elasticsearch client, index, and Embedding Model
- **AND** it MUST NOT implement a custom vector search algorithm or embedding client

### Requirement: The custom Retriever executes BM25 and KNN then applies RRF
The system SHALL execute Elasticsearch BM25 and LangChain KNN as two authorized sub-retrievals and fuse their ranked results in the application.

#### Scenario: Full-text sub-retrieval is generated
- **WHEN** Hybrid retrieval executes
- **THEN** the standard sub-retriever SHALL use a `match` query against `text`
- **AND** Elasticsearch SHALL rank that sub-retrieval with its configured BM25 similarity

#### Scenario: Vector sub-retrieval is generated
- **WHEN** Hybrid retrieval executes
- **THEN** the KNN sub-retriever SHALL query the configured `vector` field
- **AND** it SHALL use the assembly-injected candidate limits

#### Scenario: Filters are identical across sub-retrievals
- **WHEN** the custom Hybrid Retriever executes
- **THEN** the BM25 and KNN sub-retrievers SHALL apply the same authorized `accessibleBy` filter
- **AND** both SHALL apply the same allowed `docId` filter when one is present

#### Scenario: Application RRF fuses results
- **WHEN** BM25 and KNN produce ranked hits
- **THEN** the application SHALL sum `1 / (60 + rank)` for each stable `chunkId`
- **AND** it SHALL deduplicate, sort deterministically, and return at most the configured result limit

#### Scenario: Asynchronous sub-retrievals run concurrently
- **WHEN** the Graph invokes the custom Retriever asynchronously
- **THEN** BM25 and KNN SHALL start without waiting for the other to complete
- **AND** the fused result SHALL be independent of branch completion order

#### Scenario: Router does not select internal sub-retrievals
- **WHEN** Query Router creates a retrieval plan
- **THEN** it SHALL select `DOCUMENT_HYBRID`
- **AND** it MUST NOT select BM25 or KNN independently

### Requirement: Document candidates preserve available source information
The system SHALL convert LangChain Documents into serializable document candidates required by later evidence construction.

#### Scenario: Candidate shape is produced
- **WHEN** a Hybrid result is returned
- **THEN** each candidate SHALL include `chunkId`, `docId`, text, and available source metadata
- **AND** it MUST NOT contain an Elasticsearch client, Retriever, Embedding Model, callback handler, or raw provider response

#### Scenario: Unsupported Hybrid scores are not fabricated
- **WHEN** the installed LangChain Elasticsearch integration does not expose Hybrid scores or sub-retrieval ranks
- **THEN** the candidate SHALL omit those optional diagnostics
- **AND** the system MUST NOT infer, normalize, or fabricate them

### Requirement: Custom Hybrid retrieval has request-level failure behavior
The system SHALL treat the two sub-retrievals and application RRF as one retrieval request.

#### Scenario: Hybrid request succeeds with candidates
- **WHEN** the Retriever returns one or more Documents
- **THEN** `document_hybrid` SHALL return a `SUCCESS` outcome containing those candidates

#### Scenario: Hybrid request succeeds without matches
- **WHEN** the Retriever returns an empty Document list
- **THEN** `document_hybrid` SHALL return an `EMPTY` outcome

#### Scenario: Hybrid dependency fails
- **WHEN** Elasticsearch, embedding, either sub-retrieval, or fusion raises an ordinary dependency error or times out
- **THEN** `document_hybrid` SHALL return a `FAILED` outcome with no candidates
- **AND** it MUST NOT run a separate BM25, KNN, or another Retriever fallback

#### Scenario: Cancellation propagates
- **WHEN** Graph execution is cancelled
- **THEN** the system MUST NOT convert cancellation into a successful, empty, or failed outcome

### Requirement: Retrieval outcomes merge safely in RAG state
The system SHALL store Retriever results in a serializable `retrieval_outcomes` mapping keyed by Retriever ID.

#### Scenario: Document outcome is written
- **WHEN** `document_hybrid` completes
- **THEN** it SHALL write exactly one outcome under `DOCUMENT_HYBRID`
- **AND** the outcome SHALL contain status, candidates, duration and result count

#### Scenario: Parallel outcomes are merged
- **WHEN** future distinct Retriever nodes write outcomes in the same Graph superstep
- **THEN** the state reducer SHALL preserve each distinct Retriever entry
- **AND** result order MUST NOT depend on branch completion order

#### Scenario: Duplicate Retriever write is rejected
- **WHEN** the reducer receives two outcomes for the same Retriever ID in one merge
- **THEN** it SHALL fail instead of silently overwriting either outcome

### Requirement: RAG Graph executes and collects the registered document Retriever
The system SHALL extend the request-scoped RAG Graph through `document_hybrid` and `collect_retrieval_outcomes`.

#### Scenario: Document retrieval topology is compiled
- **WHEN** the production RAG Graph is assembled for this change
- **THEN** it SHALL contain `query_rewrite`, `query_router`, `document_hybrid`, and `collect_retrieval_outcomes`
- **AND** it SHALL compile without a checkpointer

#### Scenario: Selected document Retriever executes
- **WHEN** the retrieval plan selects `DOCUMENT_HYBRID`
- **THEN** Query Router SHALL transfer control to `document_hybrid`
- **AND** the collector SHALL run after the document outcome is available

#### Scenario: Collector validates completeness
- **WHEN** `collect_retrieval_outcomes` executes
- **THEN** every Retriever selected by `retrieval_plan` SHALL have one outcome
- **AND** a missing selected outcome SHALL fail the Graph

### Requirement: Hybrid retrieval is observable and testable offline
The system SHALL expose sanitized request-level diagnostics and provide deterministic offline tests plus explicit Elasticsearch integration tests.

#### Scenario: Diagnostics are recorded
- **WHEN** document retrieval completes
- **THEN** diagnostics SHALL include duration and result count
- **AND** diagnostics MUST NOT expose credentials, Elasticsearch URLs, raw exception text, or unauthorized document metadata

#### Scenario: Default tests are offline
- **WHEN** default pytest runs
- **THEN** Hybrid Retriever tests SHALL use fake stores or Retrievers
- **AND** they MUST NOT require Elasticsearch, provider credentials, Langfuse, Redis, PostgreSQL, Neo4j, or MCP

#### Scenario: Custom Hybrid behavior is verified offline
- **WHEN** infrastructure unit tests inspect the custom Retriever
- **THEN** they SHALL verify concurrent BM25/KNN calls, application RRF, deterministic deduplication, result limits, and shared filters

#### Scenario: Elasticsearch integration is explicit
- **WHEN** a developer explicitly runs the Elasticsearch integration tests
- **THEN** the tests SHALL verify real BM25/KNN retrieval, application RRF, metadata filters, empty results, mapping compatibility, and Basic License compatibility
- **AND** those tests MUST NOT run implicitly in the default test suite
