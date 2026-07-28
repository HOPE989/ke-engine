## MODIFIED Requirements

### Requirement: Chat Graph has a stable minimal topology
The system SHALL define the Business Understanding Chat Graph as a `StateGraph` over message state, structured routing state, and document evidence state.

#### Scenario: Non-business topology is compiled
- **WHEN** the Chat Graph builder is inspected or tested
- **THEN** the NON_BUSINESS execution path SHALL be `START -> business_understanding -> llm -> END`

#### Scenario: Document knowledge topology is compiled
- **WHEN** Business Understanding returns `route=BUSINESS` with intent `POLICY_RULE_QA`, `TRANSPORT_OPERATION_QA`, `COAL_SALES_QA`, or `PROFESSIONAL_KNOWLEDGE_QA`
- **THEN** the Graph SHALL route to `knowledge_rag`
- **AND** `knowledge_rag` SHALL route to `grounded_answer`
- **AND** `grounded_answer` SHALL then reach `END`

#### Scenario: Unsupported business topology is compiled
- **WHEN** Business Understanding returns `route=BUSINESS` with intent `BUSINESS_DATA_QUERY` or `OTHER_BUSINESS`
- **THEN** the Graph SHALL route to an explicit business-boundary node
- **AND** that node SHALL return a deterministic development-stage answer without invoking MCP, RAG, SQL, GraphDB, or an additional LLM
- **AND** the Graph SHALL then reach `END`

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
- **AND** the Command destination SHALL be exactly the node selected by route and supported intent
- **AND** the Graph builder MUST NOT install a separate conditional-edge router for that decision

#### Scenario: Resumed clarification owns its return transfer
- **WHEN** the clarification node resumes with valid non-blank content
- **THEN** it SHALL return LangGraph `Command(update=..., goto="business_understanding")`
- **AND** the Graph builder MUST NOT install a static clarification-to-understanding edge

#### Scenario: Message updates use LangGraph message semantics
- **WHEN** an answer node or resumed clarification returns messages
- **THEN** the Graph SHALL merge them through `MessagesState` message reduction semantics

## ADDED Requirements

### Requirement: Knowledge RAG uses an injected MCP Client
The Chat Graph SHALL obtain document evidence through a runtime-injected `RagClient` and SHALL NOT import or invoke the RAG Graph directly.

#### Scenario: Knowledge request calls RAG
- **WHEN** `knowledge_rag` executes
- **THEN** it SHALL send the current user query, up to ten preceding USER or ASSISTANT messages, the selected business intent, and `accessibleBy` containing the current user ID to `RagClient.retrieve_evidence`
- **AND** it SHALL write the returned serializable EvidencePackage and minimal references into Chat state

#### Scenario: Runtime dependencies are not checkpointed
- **WHEN** Chat state is serialized
- **THEN** it MUST NOT contain the MCP Client, MCP session, HTTP client, settings object, model client, or user principal object
- **AND** those values SHALL be supplied through `ChatRuntimeContext`

#### Scenario: RAG invocation fails
- **WHEN** the MCP Tool call raises or returns an invalid EvidencePackage
- **THEN** `knowledge_rag` SHALL fail the Graph run
- **AND** it MUST NOT invoke a local RAG fallback or fabricate evidence

### Requirement: Grounded Answer uses only returned evidence
The `grounded_answer` node SHALL generate document knowledge answers from the current question and EvidencePackage.

#### Scenario: Evidence is available
- **WHEN** the EvidencePackage contains one or more evidence items
- **THEN** `grounded_answer` SHALL invoke the runtime-injected Chat model with the question and numbered evidence
- **AND** the prompt SHALL require factual claims to use only supplied evidence
- **AND** it SHALL require numbered citations such as `[1]` that correspond to evidence item order

#### Scenario: Evidence is empty
- **WHEN** the EvidencePackage contains no evidence items
- **THEN** `grounded_answer` SHALL return the deterministic text `未检索到相关依据。`
- **AND** it MUST NOT invoke the Chat model

#### Scenario: Grounded Answer constructs no infrastructure
- **WHEN** the node is imported or invoked
- **THEN** it MUST NOT create an MCP Client, model client, database session, Elasticsearch client, or settings object

