## Purpose

Define scoped hybrid document retrieval that expands BM25 and KNN hits to parent segments, fuses them with application-level reciprocal rank fusion, and filters the final results through Bailian Qwen3 Rerank.

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

### Requirement: Hybrid retrieval preserves parent-segment ranking semantics
The system SHALL treat the expanded parent segment as the ranking unit for fusion, reranking, filtering, and final retrieval output.

#### Scenario: Child hit has a parent segment
- **WHEN** a BM25 or KNN hit contains a valid `parentChunkId`
- **THEN** that channel SHALL replace the child text and `chunkId` with the complete parent segment before RRF
- **AND** it SHALL preserve the triggering child ID as `matchedChunkId`

#### Scenario: Multiple children hit the same parent in one channel
- **WHEN** multiple ranked child hits in one BM25 or KNN channel resolve to the same parent segment
- **THEN** the expanded channel SHALL retain that parent exactly once at the highest child rank
- **AND** lower-ranked children from that channel MUST NOT add extra RRF contributions

#### Scenario: Expanded parents are fused
- **WHEN** both retrieval channels complete parent expansion and channel-level deduplication
- **THEN** RRF SHALL use the stable parent `chunkId` as the identity key
- **AND** the Qwen3 Rerank request SHALL contain the complete parent text returned by RRF rather than the triggering child text

### Requirement: RRF parent candidates are reranked and filtered by Bailian Qwen3
The system SHALL rerank the parent candidates returned by RRF with Bailian `qwen3-rerank`, apply a fixed minimum relevance score, and return a bounded final result.

#### Scenario: RRF produces ten parent candidates
- **WHEN** RRF returns ten parent Documents
- **THEN** the system SHALL submit all ten Documents in one `qwen3-rerank` request
- **AND** request `top_n` SHALL equal ten so every candidate receives a returned score

#### Scenario: RRF produces fewer than ten parent candidates
- **WHEN** RRF returns between one and nine parent Documents
- **THEN** the system SHALL submit all available Documents in one request
- **AND** request `top_n` SHALL equal the actual Document count

#### Scenario: RRF produces no candidate
- **WHEN** parent expansion and RRF return no Document
- **THEN** the system SHALL return an empty retrieval result without calling Bailian

#### Scenario: Q&A rerank request is constructed
- **WHEN** the system calls Bailian Rerank
- **THEN** the request SHALL use model `qwen3-rerank`
- **AND** it SHALL use the standalone query and the ordered RRF parent texts
- **AND** it SHALL use the English Q&A instruction `Given a web search query, retrieve relevant passages that answer the query.`

#### Scenario: Rerank results are mapped and sorted
- **WHEN** Bailian returns a valid result for every submitted parent
- **THEN** the system SHALL map each `relevance_score` to the input Document by the returned index
- **AND** it SHALL sort by score descending, original RRF rank ascending, then stable `chunkId` ascending

#### Scenario: Minimum score is applied
- **WHEN** a reranked parent has `relevance_score < 0.6`
- **THEN** the system SHALL exclude that parent from the final result
- **AND** a parent with `relevance_score == 0.6` SHALL remain eligible

#### Scenario: Final result is bounded
- **WHEN** more than five reranked parents meet the minimum score
- **THEN** the system SHALL return only the first five

#### Scenario: All reranked parents are filtered
- **WHEN** every valid reranked parent has `relevance_score < 0.6`
- **THEN** `document_hybrid` SHALL return an `EMPTY` outcome
- **AND** it MUST NOT retain a lower-scoring fallback candidate

#### Scenario: Rerank response cannot be parsed
- **WHEN** the response lacks a required index or score or references an input index that does not exist
- **THEN** the Rerank call SHALL fail
- **AND** the system MUST NOT guess, repair, or return a partial result

### Requirement: Bailian Rerank reuses existing Workspace configuration
The system SHALL use the existing OpenAI-compatible Bailian Workspace configuration for Rerank without introducing duplicate credential settings.

#### Scenario: Rerank client is assembled
- **WHEN** the RAG runtime creates the Bailian Rerank client
- **THEN** it SHALL reuse `OPENAI_API_KEY` for Bearer authorization
- **AND** it SHALL derive the Rerank endpoint from the scheme and Workspace host in `OPENAI_BASE_URL`
- **AND** the derived path SHALL be `/compatible-api/v1/reranks`

#### Scenario: Existing model clients remain unchanged
- **WHEN** the Rerank client is added
- **THEN** existing Chat and Embedding clients SHALL continue using the configured `OPENAI_BASE_URL`
- **AND** the system MUST NOT rewrite their Base URL

#### Scenario: Duplicate Bailian settings are avoided
- **WHEN** the change is configured
- **THEN** the system MUST NOT require a separate `BAILIAN_API_KEY`, `DASHSCOPE_API_KEY`, or `BAILIAN_WORKSPACE_ID`

### Requirement: Rerank policy is fixed in the application
The system SHALL implement the agreed Rerank model, instruction, threshold, and limits as fixed application policy without adding runtime configuration.

#### Scenario: Fixed Rerank pipeline executes
- **WHEN** the RAG runtime executes document retrieval
- **THEN** the existing BM25 and KNN `candidate_limit` SHALL each remain 10
- **AND** RRF SHALL return at most that same 10-candidate limit
- **AND** the hard-coded Rerank minimum score SHALL be 0.6
- **AND** the existing final `result_limit` SHALL remain 5
- **AND** `rank_constant` SHALL remain 60

#### Scenario: No new Rerank settings are required
- **WHEN** this capability is deployed
- **THEN** the system MUST NOT add settings for RRF limit, Rerank model, instruction, minimum score, retry, fallback, or endpoint probing

### Requirement: The custom Retriever executes BM25 and KNN then applies RRF
The system SHALL execute Elasticsearch BM25 and LangChain KNN as two authorized sub-retrievals, expand and deduplicate parent segments in each channel, and fuse their ranked parent results in the application.

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

#### Scenario: Application RRF fuses parent results
- **WHEN** BM25 and KNN produce parent-expanded ranked hits
- **THEN** the application SHALL sum `1 / (60 + rank)` for each stable `chunkId`
- **AND** it SHALL deduplicate and sort deterministically
- **AND** it SHALL return at most the existing candidate limit to the Rerank stage

#### Scenario: Asynchronous sub-retrievals run concurrently
- **WHEN** the Graph invokes the custom Retriever asynchronously
- **THEN** BM25 and KNN SHALL start without waiting for the other to complete
- **AND** the fused result SHALL be independent of branch completion order

#### Scenario: Router does not select internal sub-retrievals
- **WHEN** Query Router creates a retrieval plan
- **THEN** it SHALL select `DOCUMENT_HYBRID`
- **AND** it MUST NOT select BM25, KNN, RRF, or Rerank independently

### Requirement: Document candidates preserve available source information
The system SHALL convert successfully reranked LangChain Documents into serializable document candidates required by later evidence construction.

#### Scenario: Candidate shape is produced
- **WHEN** a Hybrid result passes Rerank filtering
- **THEN** each candidate SHALL include parent `chunkId`, `docId`, parent text, `rerankScore`, and available source metadata
- **AND** source metadata SHALL preserve an available `matchedChunkId`
- **AND** the candidate MUST NOT contain an Elasticsearch client, Retriever, Rerank client, Embedding Model, callback handler, credential, or raw provider response

#### Scenario: Rerank score is preserved
- **WHEN** Bailian returns a valid `relevance_score` for a retained parent
- **THEN** the candidate `rerankScore` SHALL equal that provider score without normalization or substitution

#### Scenario: Unsupported recall scores are not fabricated
- **WHEN** the installed LangChain Elasticsearch integration does not expose a recall score or sub-retrieval rank
- **THEN** the candidate SHALL omit that optional recall diagnostic
- **AND** the system MUST NOT infer, normalize, or fabricate it from `rerankScore`

### Requirement: Custom Hybrid retrieval has request-level failure behavior
The system SHALL treat BM25, KNN, parent expansion, application RRF, and Bailian Rerank as one retrieval request.

#### Scenario: Hybrid request succeeds with retained candidates
- **WHEN** Rerank returns one or more parents whose score is at least 0.6
- **THEN** `document_hybrid` SHALL return a `SUCCESS` outcome containing at most five candidates

#### Scenario: Hybrid request succeeds without recall matches
- **WHEN** parent expansion and RRF return an empty Document list
- **THEN** `document_hybrid` SHALL return an `EMPTY` outcome without calling Bailian

#### Scenario: Hybrid request succeeds without relevant rerank matches
- **WHEN** Bailian responds successfully but every candidate is below 0.6
- **THEN** `document_hybrid` SHALL return an `EMPTY` outcome

#### Scenario: Hybrid dependency fails
- **WHEN** Elasticsearch, embedding, either sub-retrieval, parent loading, fusion, Bailian HTTP, or Rerank response parsing raises an ordinary dependency error or times out
- **THEN** `document_hybrid` SHALL return a `FAILED` outcome with no candidates
- **AND** it MUST NOT run a separate BM25, KNN, another Retriever, or unreranked RRF fallback

#### Scenario: Cancellation propagates
- **WHEN** Graph execution or the asynchronous Bailian request is cancelled
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
The system SHALL expose sanitized request-level recall, parent expansion, RRF, and Rerank diagnostics and provide deterministic offline tests plus explicit Elasticsearch integration tests.

#### Scenario: Diagnostics are recorded
- **WHEN** document retrieval completes successfully or with an empty filtered result
- **THEN** diagnostics SHALL include total duration, final result count, RRF candidates, Rerank duration, model, request ID, threshold, and per-candidate Rerank rank and score
- **AND** RECALL, PARENT_EXPANSION, RRF, and RERANK candidate entries SHALL include a text preview limited to 200 characters
- **AND** diagnostics MUST NOT expose credentials, Authorization headers, provider Base URLs, complete queries, unbounded document text, raw provider responses, raw exception text, or unauthorized document metadata

#### Scenario: Default tests are offline
- **WHEN** default pytest runs
- **THEN** Hybrid Retriever and Rerank client tests SHALL use fake clients, fake stores, or HTTP mock transports
- **AND** they MUST NOT require Elasticsearch, Bailian, provider credentials, Langfuse, Redis, PostgreSQL, Neo4j, or MCP

#### Scenario: Custom Hybrid behavior is verified offline
- **WHEN** infrastructure unit tests inspect the custom Retriever
- **THEN** they SHALL verify parent expansion, application RRF, `10 + 10 → 10 → 0.6 → 5`, score/index mapping, threshold inclusion, all-filtered empty results, and provider failure behavior

#### Scenario: Bailian request construction is verified offline
- **WHEN** client unit tests inspect a Rerank request
- **THEN** they SHALL verify the derived Workspace endpoint, Bearer authorization, model, query, parent documents, Q&A instruction, dynamic `top_n`, and basic response projection

#### Scenario: Elasticsearch integration remains explicit
- **WHEN** a developer explicitly runs the Elasticsearch integration tests
- **THEN** the tests SHALL continue to verify real BM25/KNN retrieval, parent expansion, application RRF, metadata filters, empty results, mapping compatibility, and Basic License compatibility
- **AND** those tests MUST NOT call Bailian or run implicitly in the default test suite
