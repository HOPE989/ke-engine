## MODIFIED Requirements

### Requirement: Chat Graph has a stable minimal topology
The system SHALL define the Business Understanding Chat Graph as a `StateGraph` over message state and structured routing state.

#### Scenario: Non-business topology is compiled
- **WHEN** the Chat Graph builder is inspected or tested
- **THEN** the NON_BUSINESS execution path SHALL be `START -> business_understanding -> llm -> END`

#### Scenario: Business topology is compiled
- **WHEN** Business Understanding returns `route=BUSINESS`
- **THEN** the Graph SHALL route to an explicit business-boundary node
- **AND** that node SHALL return a deterministic development-stage answer without invoking RAG, SQL, or an additional LLM
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
- **AND** the Command destination SHALL be exactly the node selected by `BUSINESS`, `NON_BUSINESS`, or `CLARIFY`
- **AND** the Graph builder MUST NOT install a separate conditional-edge router for that decision

#### Scenario: Resumed clarification owns its return transfer
- **WHEN** the clarification node resumes with valid non-blank content
- **THEN** it SHALL return LangGraph `Command(update=..., goto="business_understanding")`
- **AND** the Graph builder MUST NOT install a static clarification-to-understanding edge

#### Scenario: Message updates use LangGraph message semantics
- **WHEN** an answer node or resumed clarification returns messages
- **THEN** the Graph SHALL merge them through `MessagesState` message reduction semantics

## ADDED Requirements

### Requirement: Business Understanding state is checkpointed separately from runtime dependencies
The system SHALL store the latest structured Business Understanding result in Chat Graph state while continuing to inject model clients through runtime context.

#### Scenario: Structured decision survives a checkpoint
- **WHEN** the Business Understanding node completes successfully
- **THEN** its structured result SHALL be available to the conditional router
- **AND** it SHALL be serializable by the configured PostgreSQL checkpointer

#### Scenario: Model client is not checkpointed
- **WHEN** Graph state is serialized
- **THEN** it MUST NOT contain the Chat model client, settings object, database pool, or prompt loader

### Requirement: Clarification resumes the same Graph thread
The system SHALL use the existing conversation-ID thread identifier and LangGraph `Command(resume=...)` semantics to resume a pending clarification.

#### Scenario: User supplies clarification
- **WHEN** the next completion for the same owned conversation provides non-blank content while its Graph thread is interrupted
- **THEN** that content SHALL resume the pending interrupt
- **AND** the Graph SHALL continue from the saved clarification checkpoint rather than starting at `START`

#### Scenario: Clarification answer is re-evaluated
- **WHEN** the clarification node resumes
- **THEN** it SHALL add the assistant clarification question and resumed USER answer to message state
- **AND** the next node SHALL be `business_understanding`

### Requirement: Business Understanding nodes receive models from runtime context
The system SHALL use the lifespan-initialized Chat model for both structured Business Understanding and non-business answering without constructing infrastructure inside nodes.

#### Scenario: Structured model is derived from the injected model
- **WHEN** the Business Understanding node executes
- **THEN** it SHALL use the context-provided model with the structured output schema
- **AND** it MUST NOT create a model client, read process settings directly, or open database resources
