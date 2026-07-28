## MODIFIED Requirements

### Requirement: Chat Graph has a stable minimal topology
The system SHALL define the Business Understanding Chat Graph as a `StateGraph` over message state, structured routing state, and document evidence state.

#### Scenario: Non-business topology is compiled
- **WHEN** the Chat Graph builder is inspected or tested
- **THEN** the NON_BUSINESS execution path SHALL be `START -> business_understanding -> llm -> END`

#### Scenario: Business topology is compiled
- **WHEN** Business Understanding returns `route=BUSINESS` with any supported business intent
- **THEN** the Graph SHALL route to `contextualize_query`
- **AND** `contextualize_query` SHALL route to `business_rag`
- **AND** `business_rag` SHALL route to `grounded_answer`
- **AND** `grounded_answer` SHALL then reach `END`

#### Scenario: Intent does not gate RAG
- **WHEN** Business Understanding returns `route=BUSINESS` with intent `BUSINESS_DATA_QUERY` or `OTHER_BUSINESS`
- **THEN** the Graph SHALL follow the same BUSINESS topology
- **AND** Chat MUST NOT infer a Retriever or return an unsupported boundary from the Intent

#### Scenario: Clarification topology is compiled
- **WHEN** Business Understanding returns `route=CLARIFY`
- **THEN** the Graph SHALL route to a clarification node
- **AND** that node SHALL suspend through LangGraph interrupt
- **AND** after resume it SHALL add the clarification question and user response to message state
- **AND** it SHALL route back to `business_understanding` for re-evaluation

#### Scenario: Decision nodes own execution transfer
- **WHEN** `business_understanding` produces a valid structured result
- **THEN** that node SHALL return LangGraph `Command(update=..., goto=...)`
- **AND** the Command update SHALL persist the result in `business_understanding` state
- **AND** the Command destination SHALL be exactly the node selected by route
- **AND** the Graph builder MUST NOT install a separate conditional-edge router for that decision

#### Scenario: Resumed clarification owns its return transfer
- **WHEN** the clarification node resumes with valid non-blank content
- **THEN** it SHALL return LangGraph `Command(update=..., goto="business_understanding")`
- **AND** the Graph builder MUST NOT install a static clarification-to-understanding edge

#### Scenario: Message updates use LangGraph message semantics
- **WHEN** an answer node or resumed clarification returns messages
- **THEN** the Graph SHALL merge them through `MessagesState` message reduction semantics

## ADDED Requirements

### Requirement: Chat contextualizes business queries before MCP
The Chat Graph SHALL produce a standalone query from caller-owned conversation state before invoking RAG.

#### Scenario: Multi-turn business query is contextualized
- **WHEN** a BUSINESS request contains a uniquely resolvable reference or ellipsis
- **THEN** `contextualize_query` SHALL use the current query, up to ten preceding USER/ASSISTANT messages, and Business Understanding context
- **AND** it SHALL store one standalone query that preserves all explicit constraints

#### Scenario: Clarification is required
- **WHEN** Business Understanding cannot uniquely resolve the request
- **THEN** Chat SHALL clarify before executing `contextualize_query`

### Requirement: Business RAG uses an injected MCP Client
The Chat Graph SHALL obtain document evidence through a runtime-injected `RagClient` and SHALL NOT import or invoke the RAG Graph directly.

#### Scenario: Business request calls RAG
- **WHEN** `business_rag` executes
- **THEN** it SHALL send only the standalone query and `accessibleBy` containing the current user ID to `RagClient.retrieve_evidence`
- **AND** it SHALL write the returned serializable EvidencePackage and minimal references into Chat state

#### Scenario: Runtime dependencies are not checkpointed
- **WHEN** Chat state is serialized
- **THEN** it MUST NOT contain the MCP Client, MCP session, HTTP client, settings object, model client, or user principal object
- **AND** those values SHALL be supplied through `ChatRuntimeContext`

#### Scenario: RAG invocation fails
- **WHEN** the MCP Tool call raises or returns an invalid EvidencePackage
- **THEN** `business_rag` SHALL fail the Graph run
- **AND** it MUST NOT invoke a local RAG fallback or fabricate evidence

### Requirement: Grounded Answer uses only returned evidence
The `grounded_answer` node SHALL generate document knowledge answers from the current question and EvidencePackage.

#### Scenario: Evidence is available
- **WHEN** the EvidencePackage contains one or more evidence items
- **THEN** `grounded_answer` SHALL invoke the runtime-injected Chat model with the question and numbered evidence
- **AND** the prompt SHALL require factual claims to use only supplied evidence
- **AND** it SHALL require numbered citations such as `[1]` that correspond to evidence item order

#### Scenario: Intent selects answer policy
- **WHEN** grounded answer executes for a BUSINESS request
- **THEN** it SHALL select the domain answer Prompt from the stored business Intent
- **AND** the selected Prompt MUST NOT choose or override a Retriever

#### Scenario: Evidence is empty
- **WHEN** the EvidencePackage contains no evidence items
- **THEN** `grounded_answer` SHALL return the deterministic text `未检索到相关依据。`
- **AND** it MUST NOT invoke the Chat model

#### Scenario: Grounded Answer constructs no infrastructure
- **WHEN** the node is imported or invoked
- **THEN** it MUST NOT create an MCP Client, model client, database session, Elasticsearch client, or settings object
