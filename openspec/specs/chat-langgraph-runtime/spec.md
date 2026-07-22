# Chat LangGraph Runtime

## Purpose

Define the production Chat Graph topology, runtime dependency boundaries, PostgreSQL checkpoint semantics, and failure consistency model.
## Requirements
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

### Requirement: LLM node receives its model from runtime context
The system SHALL inject the initialized Chat model into Graph execution context.

#### Scenario: Node invokes the injected model
- **WHEN** the `llm` node executes
- **THEN** it SHALL pass the current state messages to the context-provided model
- **AND** it SHALL return the resulting complete AI message as a state update

#### Scenario: Node does not construct infrastructure
- **WHEN** the `llm` node is imported or invoked
- **THEN** it MUST NOT create a model client, read process settings directly, or open database resources

### Requirement: Conversation ID is the checkpoint thread identifier
The system SHALL use the business conversation ID as the LangGraph configurable `thread_id` without persisting a second thread identifier.

#### Scenario: Same conversation resumes Graph context
- **WHEN** two successful turns execute for the same conversation
- **THEN** both runs SHALL use the same decimal-string thread ID
- **AND** the later run SHALL be able to read the earlier successful Graph message state

#### Scenario: Different conversations are isolated
- **WHEN** Graph runs use different conversation IDs
- **THEN** their checkpoint histories and message state SHALL remain isolated

### Requirement: PostgreSQL checkpointer uses dedicated runtime resources
The system SHALL use LangGraph's asynchronous PostgreSQL saver against the existing configured PostgreSQL database.

#### Scenario: Business and checkpoint access use separate pools
- **WHEN** Chat infrastructure starts
- **THEN** business repositories SHALL continue using the SQLAlchemy async pool
- **AND** the LangGraph saver SHALL use a dedicated psycopg async connection pool
- **AND** both pools SHALL resolve from the existing `DATABASE_URL`

#### Scenario: Saver manages its internal schema
- **WHEN** checkpoint storage is initialized
- **THEN** the application SHALL invoke the saver-supported setup behavior
- **AND** Alembic, ORM models, and business repositories MUST NOT create, query, or mutate LangGraph internal tables

#### Scenario: Production startup cannot silently lose persistence
- **WHEN** the PostgreSQL saver cannot initialize
- **THEN** Chat API startup SHALL fail
- **AND** it MUST NOT fall back to an in-memory saver

### Requirement: Production Graph is compiled in application lifespan
The system SHALL initialize the model, checkpointer, and compiled production Chat Graph through FastAPI lifespan-managed resources.

#### Scenario: Graph compiles after dependencies are ready
- **WHEN** the Chat API starts
- **THEN** the model and saver SHALL be initialized before the Graph is compiled
- **AND** request handlers SHALL receive the compiled Graph through application dependencies

#### Scenario: Runtime resources close on shutdown
- **WHEN** the Chat API shuts down
- **THEN** it SHALL stop accepting new Graph runs
- **AND** it SHALL close the LangGraph connection pool after managed producer tasks have been handled

#### Scenario: Importing a module does not create the production Graph
- **WHEN** Chat modules are imported outside the running service
- **THEN** import alone MUST NOT open runtime connections or compile a production Graph bound to mutable global resources

### Requirement: Node failure preserves the last successful superstep
The system SHALL treat successful LangGraph supersteps as the checkpoint consistency boundary.

#### Scenario: Failed node output does not enter Graph state
- **WHEN** the `llm` node raises before returning its state update
- **THEN** partial streamed content SHALL not become a complete AI message in Graph state
- **AND** the usable checkpoint SHALL remain at the previous successful superstep

#### Scenario: Runtime failure provenance remains internal
- **WHEN** LangGraph records failure metadata in its internal persistence
- **THEN** business APIs SHALL not expose that metadata as a user-visible message
- **AND** business code SHALL not rewrite the internal tables to simulate success

### Requirement: Process failure may discard in-flight node output
The system SHALL accept loss of output produced after the current thread's last successful checkpoint when the service process terminates unexpectedly.

#### Scenario: Process terminates during LLM execution
- **WHEN** the process stops before the LLM node and ASSISTANT business transaction complete
- **THEN** uncheckpointed token output SHALL be discarded
- **AND** no partial ASSISTANT business message SHALL be considered durable
- **AND** the system SHALL not require an automatic recovery scan in this version

### Requirement: LLM node has no automatic retry policy
The system MUST NOT automatically retry the first-version streaming LLM node after a failed attempt.

#### Scenario: Node attempt fails after streaming output
- **WHEN** an LLM attempt fails after emitting one or more token events
- **THEN** the Graph run SHALL fail rather than starting a second automatic attempt whose output could mix with the first

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

### Requirement: Local Studio reuses the production Graph topology
The system SHALL expose a local Agent Server graph that binds a development Chat model to the existing Chat graph builder without duplicating node or edge declarations.

#### Scenario: Studio graph is loaded
- **WHEN** Agent Server loads the graph declared in `langgraph.json`
- **THEN** the Studio adapter SHALL create the configured Chat model and call the existing graph builder in bound-model mode
- **AND** the resulting graph SHALL retain the same node names, state, edges and `Command(goto)` routing as the production Graph

#### Scenario: Studio runs without production runtime context
- **WHEN** Studio invokes the bound graph without a `BaseChatModel` runtime context payload
- **THEN** the model-dependent nodes SHALL use the model bound by the adapter
- **AND** the production builder default SHALL continue to use `ChatRuntimeContext`

### Requirement: Studio remains a development-only adapter
The Studio adapter MUST NOT initialize the production FastAPI Chat lifespan or its business resources.

#### Scenario: Studio module is loaded
- **WHEN** the Studio graph factory is imported or called
- **THEN** it MUST NOT create the business database Session, production PostgreSQL saver, Redis client, conversation lock, producer registry, SSE transport or title model
- **AND** Agent Server SHALL own development persistence

#### Scenario: Langfuse is unavailable in Studio
- **WHEN** Studio starts without usable Langfuse resources
- **THEN** the graph SHALL remain runnable without tracing
