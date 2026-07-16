## ADDED Requirements

### Requirement: Chat Graph has a stable minimal topology
The system SHALL define the first-version Chat Graph as a `StateGraph` over message state with one stable `llm` node.

#### Scenario: Graph topology is compiled
- **WHEN** the Chat Graph builder is inspected or tested
- **THEN** its only execution path SHALL be `START -> llm -> END`

#### Scenario: Message updates use LangGraph message semantics
- **WHEN** the LLM node returns an AI message
- **THEN** the Graph SHALL merge it through `MessagesState` message reduction semantics

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
