## ADDED Requirements

### Requirement: The next conversation message resumes a pending clarification
The system SHALL use the existing completion request content as the resume value when the owned conversation's LangGraph thread has a pending Business Understanding clarification.

#### Scenario: Owned pending conversation resumes
- **WHEN** the current user submits non-blank content with an owned conversation ID whose Graph thread is waiting for clarification
- **THEN** the backend SHALL persist the content as the next USER business message
- **AND** it SHALL resume the existing Graph thread with that content
- **AND** it MUST NOT start a new Graph input at `START`

#### Scenario: Conversation without pending clarification starts a normal turn
- **WHEN** the current user submits content for a conversation whose Graph thread is not interrupted
- **THEN** the backend SHALL execute the normal new-turn Graph input behavior

#### Scenario: Client does not control resume internals
- **WHEN** a client submits a completion request
- **THEN** the public request MUST NOT accept a checkpoint identifier, interrupt identifier, raw LangGraph command, route override, or intent override

#### Scenario: Pending state remains owner-protected
- **WHEN** a user submits a completion for a conversation owned by another user
- **THEN** the API SHALL return HTTP 404
- **AND** it MUST NOT reveal whether that conversation has a pending interrupt

### Requirement: Resume input preserves existing durability order
The system SHALL commit the resumed USER business message before starting or resuming Graph execution.

#### Scenario: Resume begins after user commit
- **WHEN** a pending clarification is resumed
- **THEN** the conversation and USER message transaction SHALL commit before `Command(resume=...)` is executed
- **AND** the first SSE event SHALL remain the existing durable `metadata` event

#### Scenario: User persistence failure prevents resume
- **WHEN** the USER business-message transaction fails
- **THEN** the backend MUST NOT resume the LangGraph thread
- **AND** the prior clarification checkpoint SHALL remain pending

### Requirement: One conversation has at most one active completion
The system SHALL guard the complete completion lifecycle for one conversation with one coarse Redis distributed lock while allowing different conversations to execute independently.

#### Scenario: Completion lock covers persistence and Graph execution
- **WHEN** the backend accepts a completion for an owned conversation
- **THEN** it SHALL acquire the conversation lock before persisting the USER message
- **AND** it SHALL hold the same lock through checkpoint inspection, Graph start or resume, ASSISTANT persistence, and terminal completion handling

#### Scenario: Concurrent completion fails before user persistence
- **WHEN** the same conversation already has an active completion lock
- **THEN** another completion request for that conversation SHALL fail with a conflict
- **AND** it MUST NOT persist another USER message
- **AND** it MUST NOT inspect or mutate the LangGraph checkpoint

#### Scenario: Ownership remains hidden before lock state
- **WHEN** a user submits a completion for a missing or foreign-owned conversation
- **THEN** the API SHALL return the same HTTP 404 behavior
- **AND** it MUST NOT reveal whether that conversation currently has an active lock

#### Scenario: Disconnect does not release active work
- **WHEN** the HTTP subscriber disconnects after the completion is accepted
- **THEN** the background completion SHALL retain the conversation lock
- **AND** it SHALL release the lock only after its success, failure, cancellation, or shutdown cleanup path finishes

#### Scenario: Redis lock infrastructure is unavailable
- **WHEN** the backend cannot acquire or verify the conversation lock because Redis is unavailable
- **THEN** the completion SHALL fail closed
- **AND** it MUST NOT persist the USER message or start Graph execution
