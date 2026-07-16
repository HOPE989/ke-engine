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
