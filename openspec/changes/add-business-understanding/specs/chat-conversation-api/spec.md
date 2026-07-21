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
