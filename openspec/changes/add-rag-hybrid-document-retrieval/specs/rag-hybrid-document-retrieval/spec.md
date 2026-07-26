## ADDED Requirements

### Requirement: Hybrid document retrieval has a scoped request contract
The system SHALL retrieve documents using one non-blank `standalone_query` and a server-provided document retrieval scope.

#### Scenario: Access scope is present
- **WHEN** `DOCUMENT_HYBRID` executes
- **THEN** the request SHALL contain at least one non-blank authorized `accessibleBy` value
- **AND** it MAY contain a server-provided set of allowed `docId` values

#### Scenario: Scope is missing or invalid
- **WHEN** the document retrieval scope is missing, empty, malformed, or caller-controlled without server validation
- **THEN** the Retriever SHALL fail before querying Elasticsearch
- **AND** it MUST NOT perform an unfiltered search

#### Scenario: Filters are consistent across channels
- **WHEN** Dense and BM25 searches execute for one request
- **THEN** both searches SHALL apply the same authorized `accessibleBy` filter
- **AND** both SHALL apply the same allowed `docId` filter when one is present

#### Scenario: Scope is bound per request
- **WHEN** the Graph prepares `DOCUMENT_HYBRID` for one request
- **THEN** it SHALL create a Retriever instance with an immutable validated scope
- **AND** it MUST NOT mutate filters on a process-wide Retriever shared by concurrent requests

### Requirement: Hybrid document retrieval implements the LangChain Retriever contract
The system SHALL implement `DOCUMENT_HYBRID` as a subclass of LangChain `BaseRetriever` that composes Elasticsearch dependencies.

#### Scenario: Asynchronous retrieval uses the standard contract
- **WHEN** `document_hybrid` executes
- **THEN** it SHALL invoke the Retriever through `ainvoke` with the standalone query and Runnable config
- **AND** the Retriever SHALL return a list of LangChain `Document` values

#### Scenario: Retriever preserves callback propagation
- **WHEN** Runnable callbacks are supplied for Graph execution
- **THEN** the Retriever invocation SHALL propagate them through the LangChain Retriever lifecycle
- **AND** it MUST NOT create an unrelated callback chain

#### Scenario: Elasticsearch infrastructure is composed
- **WHEN** the Hybrid Retriever is assembled
- **THEN** it SHALL compose the existing `ElasticsearchStore`, Elasticsearch client, and Embedding Model
- **AND** it MUST NOT duplicate vector-store connection or embedding infrastructure

#### Scenario: Graph state remains domain shaped
- **WHEN** the Retriever returns LangChain Documents
- **THEN** `document_hybrid` SHALL convert them into serializable document candidates and one `RetrievalOutcome`
- **AND** LangChain or Elasticsearch runtime objects MUST NOT be stored in `RagState`

### Requirement: Hybrid document retrieval runs Dense and BM25 concurrently
The system SHALL execute Dense and BM25 as internal channels of one `DOCUMENT_HYBRID` Retriever.

#### Scenario: Both channels are available
- **WHEN** the Hybrid Retriever receives a valid request through `ainvoke`
- **THEN** Dense and BM25 searches SHALL begin without waiting for the other channel to complete
- **AND** each channel SHALL use the assembly-injected candidate limit and timeout

#### Scenario: Router does not select internal channels
- **WHEN** Query Router creates a retrieval plan
- **THEN** it SHALL select `DOCUMENT_HYBRID`
- **AND** it MUST NOT select Dense or BM25 independently

### Requirement: Hybrid document retrieval fuses candidates deterministically
The system SHALL fuse Dense and BM25 candidates with reciprocal rank fusion and deduplicate them by `chunkId`.

#### Scenario: Candidate appears in both channels
- **WHEN** Dense and BM25 return the same `chunkId`
- **THEN** the fused result SHALL contain that chunk exactly once
- **AND** its fused score SHALL include the reciprocal-rank contribution from both channels

#### Scenario: Candidate appears in one channel
- **WHEN** only one channel returns a `chunkId`
- **THEN** the candidate SHALL remain eligible using that channel's reciprocal-rank contribution

#### Scenario: Result order is deterministic
- **WHEN** the same channel results arrive in different completion orders
- **THEN** the fused candidate order SHALL remain identical
- **AND** ties SHALL be resolved using stable rank and `chunkId` fields

#### Scenario: Final candidate budget is enforced
- **WHEN** fusion produces more candidates than the assembly-injected final limit
- **THEN** the Retriever SHALL return only the highest-ranked candidates within that limit

### Requirement: Document candidates preserve source information
The system SHALL return serializable document candidates with the source data required by later evidence construction.

#### Scenario: Candidate shape is produced
- **WHEN** a fused candidate is returned
- **THEN** it SHALL include `chunkId`, `docId`, text, source metadata, fused score, and available channel rank and score diagnostics
- **AND** it MUST NOT contain an Elasticsearch client, embedding model, callback handler, or raw provider response

### Requirement: Hybrid document retrieval has explicit channel failure behavior
The system SHALL isolate ordinary Dense and BM25 channel failures without hiding complete Retriever failure.

#### Scenario: One channel fails
- **WHEN** one channel raises an ordinary dependency error or times out and the other returns candidates
- **THEN** the Retriever SHALL fuse the successful channel's candidates
- **AND** returned Document metadata SHALL identify the failed channel without raw exception text

#### Scenario: One channel fails without usable candidates
- **WHEN** one channel raises an ordinary dependency error or times out and the other returns no candidates
- **THEN** the Retriever SHALL raise a stable retrieval failure containing structured failed-channel identifiers
- **AND** `document_hybrid` SHALL convert it into a `FAILED` outcome with no candidates

#### Scenario: Both channels fail
- **WHEN** both channels raise ordinary dependency errors or time out
- **THEN** the Retriever SHALL raise a stable retrieval failure containing structured failed-channel identifiers
- **AND** `document_hybrid` SHALL return a `FAILED` outcome with no candidates
- **AND** it MUST NOT silently call another Retriever

#### Scenario: Search succeeds without matches
- **WHEN** both channels complete successfully without candidates
- **THEN** the Retriever SHALL return an `EMPTY` outcome

#### Scenario: Cancellation propagates
- **WHEN** Graph execution is cancelled
- **THEN** the Retriever MUST NOT convert cancellation into a successful, empty, or failed outcome

### Requirement: Retrieval outcomes merge safely in RAG state
The system SHALL store Retriever results in a serializable `retrieval_outcomes` mapping keyed by Retriever ID.

#### Scenario: Document outcome is written
- **WHEN** `document_hybrid` completes
- **THEN** it SHALL write exactly one outcome under `DOCUMENT_HYBRID`
- **AND** the outcome SHALL contain status, candidates, duration and channel/result counts

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
The system SHALL expose sanitized retrieval diagnostics and provide deterministic offline tests plus explicit Elasticsearch integration tests.

#### Scenario: Diagnostics are recorded
- **WHEN** document retrieval completes
- **THEN** diagnostics SHALL include duration, per-channel candidate count, fused result count, and failed channel identifiers
- **AND** diagnostics MUST NOT expose credentials, Elasticsearch URLs, raw exception text, or unauthorized document metadata

#### Scenario: Default tests are offline
- **WHEN** default pytest runs
- **THEN** Hybrid Retriever tests SHALL use fake Dense and BM25 adapters
- **AND** they MUST NOT require Elasticsearch, provider credentials, Langfuse, Redis, PostgreSQL, Neo4j, or MCP

#### Scenario: Elasticsearch integration is explicit
- **WHEN** a developer explicitly runs the Elasticsearch integration tests
- **THEN** the tests SHALL verify Dense search, BM25 search, metadata filters, RRF fusion, empty results, and mapping compatibility against a configured test index
- **AND** those tests MUST NOT run implicitly in the default test suite
