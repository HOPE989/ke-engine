## ADDED Requirements

### Requirement: Query Rewrite has a caller-independent input contract

The system SHALL accept one non-blank `original_query`, optional ordered `conversation_context`, and optional structured `business_context` without reading a caller's conversation database.

#### Scenario: Current query is provided independently

- **WHEN** a caller invokes Query Rewrite
- **THEN** the request SHALL contain one non-blank `original_query`
- **AND** the current query MUST NOT be duplicated inside `conversation_context`

#### Scenario: Conversation context is optional

- **WHEN** the original query is already independent or the caller has no conversation history
- **THEN** the caller MAY omit `conversation_context`
- **AND** Query Rewrite SHALL still produce one result

#### Scenario: Context remains caller-owned

- **WHEN** Query Rewrite receives an input
- **THEN** it MUST NOT accept a `conversation_id` for loading external history
- **AND** it MUST NOT access Chat persistence, checkpoints, Redis, or another caller-owned memory store

#### Scenario: Business context is advisory

- **WHEN** `business_context` contains an intent or entities derived by the caller
- **THEN** Query Rewrite MAY use those values to resolve the current query
- **AND** it MUST NOT override an explicit conflicting value in `original_query`

### Requirement: Query Rewrite produces one retrieval-oriented standalone query

The system SHALL transform the input into exactly one non-blank `standalone_query` that can be understood without the supplied conversation history and is concise enough for retrieval.

#### Scenario: Context-dependent reference is resolved

- **WHEN** `original_query` contains a pronoun or ellipsis whose referent is uniquely determined by the supplied context
- **THEN** `standalone_query` SHALL replace that reference with the determined entity or condition
- **AND** the result SHALL remain one query

#### Scenario: Conversational noise is removed

- **WHEN** `original_query` contains greetings, politeness, repeated wording, or other text that does not change the information need
- **THEN** `standalone_query` SHALL omit that noise
- **AND** it SHALL express the same information need in a retrieval-oriented form

#### Scenario: Clear terminology is normalized

- **WHEN** the input contains an unambiguous typo, alias, entity spelling, or domain term that can be normalized from the supplied information
- **THEN** `standalone_query` SHALL use the normalized expression
- **AND** it MUST NOT introduce a different entity

#### Scenario: Hard constraints are preserved

- **WHEN** the input contains an entity, time, number, range, negation, comparison, ownership, version, or other retrieval-changing constraint
- **THEN** `standalone_query` SHALL preserve that constraint
- **AND** it MUST NOT generalize the query in a way that removes the constraint

#### Scenario: Explicit current input wins over history

- **WHEN** conversation or business context conflicts with an explicit value in `original_query`
- **THEN** `standalone_query` SHALL preserve the explicit current value
- **AND** it MUST NOT silently replace it with the historical value

#### Scenario: Unsupported facts are not invented

- **WHEN** neither the original query nor supplied context establishes a fact
- **THEN** Query Rewrite MUST NOT add that fact merely to make the query appear complete

#### Scenario: Already suitable query remains semantically stable

- **WHEN** `original_query` is already independent, concise, correctly normalized, and suitable for retrieval
- **THEN** `standalone_query` SHALL remain semantically equivalent
- **AND** the system MAY return the original text unchanged

#### Scenario: Multi-query expansion is absent

- **WHEN** Query Rewrite completes successfully
- **THEN** its output SHALL contain exactly one `standalone_query`
- **AND** it MUST NOT return query variants, subquestions, research steps, route decisions, SQL, or Cypher

### Requirement: Query Rewrite uses validated structured model output

The system SHALL invoke the assembly-injected Chat model with a versioned Prompt and validate the response as a single-field `QueryRewriteResult`.

#### Scenario: Structured output succeeds

- **WHEN** the model returns a valid non-blank `standalone_query`
- **THEN** the node SHALL store that value as the query supplied to the next future RAG stage
- **AND** it SHALL record the Rewrite status as successful

#### Scenario: Prompt separates current query from context

- **WHEN** the model invocation is constructed
- **THEN** the Prompt SHALL identify `original_query`, `conversation_context`, and `business_context` as separate inputs
- **AND** it SHALL state that the current query has precedence over conflicting context

#### Scenario: Prompt forbids answering and decomposition

- **WHEN** the model receives the Query Rewrite Prompt
- **THEN** the Prompt SHALL instruct it to rewrite rather than answer the question
- **AND** it SHALL forbid multi-query expansion and research planning

### Requirement: Query Rewrite degrades to the original query

The system SHALL preserve retrieval availability by using `original_query` as `standalone_query` when the Rewrite attempt fails.

#### Scenario: Model invocation fails

- **WHEN** the model invocation raises an ordinary exception
- **THEN** the node SHALL set `standalone_query` to `original_query`
- **AND** it SHALL record a degraded Rewrite status and a bounded failure code
- **AND** it MUST NOT retry the model call

#### Scenario: Structured output is invalid

- **WHEN** the model response is empty, blank, malformed, or fails `QueryRewriteResult` validation
- **THEN** the node SHALL set `standalone_query` to `original_query`
- **AND** it SHALL record the same observable degradation semantics as an invocation failure

#### Scenario: Cancellation is not converted into fallback

- **WHEN** Graph execution is cancelled by the runtime
- **THEN** Query Rewrite MUST NOT convert that cancellation into a successful fallback result

#### Scenario: Fallback remains one query

- **WHEN** Rewrite degrades
- **THEN** only `original_query` SHALL continue as `standalone_query`
- **AND** the system MUST NOT execute both the original and a partial rewritten value

### Requirement: Query Rewrite is the first stage of the RAG Graph

The system SHALL add Query Rewrite to the request-scoped, pipeline-level RAG Graph, whose current topology is `START -> query_rewrite -> END`.

#### Scenario: Initial RAG topology is compiled

- **WHEN** the RAG Graph builder is inspected or tested for this increment
- **THEN** it SHALL contain exactly one business node named `query_rewrite`
- **AND** it SHALL connect `START` to `query_rewrite` and `query_rewrite` to `END`
- **AND** its top-level state and builder SHALL represent the RAG pipeline rather than a Query Rewrite subgraph

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
- **THEN** it SHALL contain only request data, result data, status, warnings, and bounded diagnostic values
- **AND** it MUST NOT contain a model client, Langfuse client, callback handler, settings object, database connection, or external service client

### Requirement: Query Rewrite supports callback-based observability

The system SHALL preserve caller-provided LangChain callbacks through the Graph and model invocation without making observability a business dependency.

#### Scenario: Callback is supplied

- **WHEN** a caller invokes the RAG Graph with a Langfuse `CallbackHandler`
- **THEN** the Graph and Query Rewrite model call SHALL be observable beneath that callback
- **AND** the observation SHALL include the original input, actual `standalone_query`, Rewrite status, and fallback warning when present

#### Scenario: Callback is absent

- **WHEN** a caller invokes the Graph without Langfuse resources
- **THEN** Query Rewrite behavior and output SHALL remain unchanged

#### Scenario: Fallback is observable

- **WHEN** Rewrite degrades to `original_query`
- **THEN** Graph state SHALL include a warning suitable for a future `EvidencePackage.warnings`
- **AND** diagnostic text MUST NOT expose credentials or raw provider secrets

### Requirement: Query Rewrite has offline tests and an explicit live-model evaluation path

The system SHALL provide deterministic default tests and a separate opt-in path for evaluating the production node with a configured live model.

#### Scenario: Default tests are offline

- **WHEN** the default backend test suite runs
- **THEN** Query Rewrite tests SHALL use fake or stub Chat models
- **AND** they MUST NOT require network access, provider credentials, Langfuse, Redis, PostgreSQL, Elasticsearch, or MCP

#### Scenario: Fixtures cover semantic preservation

- **WHEN** the repository Query Rewrite cases are inspected
- **THEN** they SHALL cover context resolution, conversational noise, terminology normalization, already-standalone input, and preservation of entity, time, numeric, negation, comparison, and ownership constraints
- **AND** they SHALL provide a human reference query and case-specific semantic review guidance without requiring exact wording

#### Scenario: Code evaluators remain objective

- **WHEN** an offline or Langfuse code evaluator scores a Query Rewrite result
- **THEN** it MAY validate non-blank structured output, status values, and fallback consistency
- **AND** it MUST NOT represent semantic quality with keyword inclusion, token overlap, regular expressions, edit distance, or reference-query exact match

#### Scenario: Semantic quality uses human or model judgment

- **WHEN** an experiment evaluates semantic equivalence, context resolution, constraint preservation, retrieval readiness, or unsupported invention
- **THEN** those dimensions SHALL be scored by a human reviewer or an LLM-as-a-Judge using an explicit rubric
- **AND** the evaluation SHALL retain a short reason that can be inspected with the score

#### Scenario: LLM Judge is calibrated before gating

- **WHEN** LLM-as-a-Judge scores are considered for an automated quality gate
- **THEN** the Judge SHALL first be compared with human annotations on representative Query Rewrite outputs
- **AND** uncalibrated Judge scores MUST NOT gate CI, releases, or automatic Prompt selection

#### Scenario: Live evaluation runs the production node

- **WHEN** a developer explicitly runs the live-model evaluation command with valid model configuration
- **THEN** it SHALL invoke the production Query Rewrite node against the repository cases
- **AND** it SHALL report each original query, resulting standalone query, Rewrite status, objective contract checks, and any separately produced human or LLM Judge scores

#### Scenario: Live evaluation is not a default gate

- **WHEN** default pytest or CI runs without provider credentials
- **THEN** the live-model evaluation SHALL not run implicitly
- **AND** its absence MUST NOT be reported as a successful live evaluation
