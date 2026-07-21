## ADDED Requirements

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
