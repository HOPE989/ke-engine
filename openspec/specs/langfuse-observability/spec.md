# langfuse-observability Specification

## Purpose
TBD - created by archiving change add-langfuse-observability. Update Purpose after archive.
## Requirements
### Requirement: Chat completion tracing is fail-open
The system SHALL trace each accepted Chat completion as one Langfuse root observation when complete Langfuse resources are available, and MUST preserve the same completion behavior when Langfuse is unavailable or fails.

#### Scenario: Configured completion is traced
- **WHEN** a Chat completion is accepted while valid Langfuse resources are available
- **THEN** the system SHALL create one `chat-completion` root observation containing the raw turn input, conversation session, user identity and final terminal output
- **AND** the LangGraph invocation SHALL receive the Langfuse callback so Graph, node and model activity is nested beneath that trace

#### Scenario: Langfuse configuration is incomplete
- **WHEN** the Chat API or Studio starts without a complete public key, secret key and base URL
- **THEN** the system SHALL continue without Langfuse tracing
- **AND** Graph, checkpoint, Redis, database and SSE behavior MUST remain unchanged

#### Scenario: Trace lifecycle fails
- **WHEN** Langfuse observation creation, update, cleanup or shutdown raises an exception
- **THEN** the system SHALL log the observability failure
- **AND** it MUST NOT replace a successful completion or mask the original business exception

### Requirement: Trace content is complete but bounded to LLM behavior
The system SHALL record complete user messages, Prompt content, model input, model output and structured business-understanding output without a sampling, masking or tracing-enabled switch.

#### Scenario: Full model context is captured
- **WHEN** a traced Graph node invokes a model
- **THEN** the Langfuse observation SHALL include the complete model input and output allowed by the callback integration

#### Scenario: Infrastructure noise is excluded
- **WHEN** a completion emits SSE deltas, uses a Redis lock, persists checkpoints or executes SQL
- **THEN** the system MUST NOT create one Langfuse observation per SSE delta or explicitly record lock tokens, SQL statements or raw checkpoint serialization
- **AND** the title model MUST NOT inherit the Chat Graph callback

### Requirement: Langfuse resources have application lifetime
The Chat API SHALL create at most one Langfuse client/handler pair for an application lifespan and SHALL close it after managed completion producers stop.

#### Scenario: Application shuts down with tracing
- **WHEN** the Chat API lifespan exits with Langfuse resources present
- **THEN** the producer registry SHALL stop before Langfuse shutdown
- **AND** Langfuse shutdown SHALL occur before Redis, the PostgreSQL saver and the business database are released
