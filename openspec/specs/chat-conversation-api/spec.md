# Chat Conversation API

## Purpose

Define the current-user conversation, message-history, and completion input contracts for the production Chat API.
## Requirements
### Requirement: Current-user conversation listing
The system SHALL expose `GET /api/v1/chat/conversations` to list conversations owned by the authenticated principal.

#### Scenario: Conversations are returned in stable newest-first order
- **WHEN** the current user requests a conversation page
- **THEN** the system SHALL return only that user's non-deleted conversations ordered by `(updated_at DESC, id DESC)`
- **AND** the response SHALL include an opaque cursor for the next page when more rows exist

#### Scenario: One user's list does not expose another user's conversations
- **WHEN** two users have persisted conversations
- **THEN** each user's list SHALL contain only conversations owned by that user

### Requirement: Current-user message history
The system SHALL expose `GET /api/v1/chat/conversations/{conversation_id}/messages` to return the authenticated user's persisted business messages for a conversation.

#### Scenario: Messages are returned in deterministic chronological order
- **WHEN** the owner requests a conversation's message history
- **THEN** the system SHALL return messages ordered by `(created_at ASC, id ASC)`
- **AND** cursor pagination SHALL preserve that order without offset-based page drift

#### Scenario: Runtime-only state is not exposed as message history
- **WHEN** message history is requested
- **THEN** the response SHALL be sourced from the business `messages` table
- **AND** the response MUST NOT be assembled from LangGraph checkpoint tables

### Requirement: Conversation ownership is concealed
The system SHALL authorize all conversation-specific operations against the authenticated principal.

#### Scenario: Missing conversation returns not found
- **WHEN** the requested conversation ID does not exist
- **THEN** the system SHALL return HTTP 404

#### Scenario: Another user's conversation returns not found
- **WHEN** the requested conversation exists but belongs to another user
- **THEN** the system SHALL return HTTP 404 rather than revealing that the resource exists

### Requirement: Completion input selects or creates a conversation
The system SHALL accept `POST /api/v1/chat/completions` with non-empty `content` and an optional `conversation_id`.

#### Scenario: First message creates a conversation
- **WHEN** the current user submits valid content without a conversation ID
- **THEN** the backend SHALL generate a new conversation ID
- **AND** it SHALL persist an ACTIVE conversation owned by the current user
- **AND** it SHALL derive the conversation title from the normalized first message, truncated to the persistence limit

#### Scenario: Existing conversation receives the next user message
- **WHEN** the current user submits valid content with an owned conversation ID
- **THEN** the system SHALL append the USER message to that conversation
- **AND** it SHALL update the conversation's activity timestamp

#### Scenario: Blank content is rejected
- **WHEN** submitted content is empty or contains only whitespace
- **THEN** the system SHALL reject the request before creating a conversation or message

### Requirement: Chat identifiers are JSON strings
The system SHALL encode Snowflake-backed BIGINT identifiers as decimal strings at HTTP and SSE boundaries.

#### Scenario: API response serializes identifiers safely
- **WHEN** a conversation or message identifier is returned to a client
- **THEN** the identifier SHALL be represented as a JSON string without numeric precision loss

#### Scenario: Conversation identifier is accepted as a decimal string
- **WHEN** a completion request supplies a conversation ID
- **THEN** the API SHALL validate it as a decimal string representing a supported Snowflake identifier

### Requirement: Chat model selection is server-controlled
The system SHALL use the server's configured Chat model for completion requests.

#### Scenario: Client cannot select an arbitrary model
- **WHEN** a client submits a completion request
- **THEN** the public request contract MUST NOT allow that client to override the configured model name

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
