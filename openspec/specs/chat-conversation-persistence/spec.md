## Purpose

Define the authoritative PostgreSQL persistence contract for minimal Chat conversations and user-visible messages.

## Requirements

### Requirement: Conversation persistence schema
The system SHALL persist business conversations in a `conversations` table with a minimal, user-owned schema.

#### Scenario: Conversation table columns are defined
- **WHEN** the Chat persistence migration is applied
- **THEN** `conversations.id` SHALL be a `BIGINT` primary key without a database identity or server-generated default
- **AND** `conversations.user_id` SHALL be `VARCHAR(255) NOT NULL`
- **AND** `conversations.title` SHALL be `VARCHAR(255) NOT NULL`
- **AND** `conversations.status` SHALL be `VARCHAR(32) NOT NULL DEFAULT 'ACTIVE'`
- **AND** `conversations.created_at` and `conversations.updated_at` SHALL be timezone-aware timestamps with current-time server defaults

#### Scenario: Conversation table remains minimal
- **WHEN** the `conversations` table is inspected
- **THEN** it MUST NOT contain `tenant_id`, `project_id`, `thread_id`, a second conversation identifier, model settings, or aggregate counter columns

### Requirement: Conversation lifecycle constraint
The system SHALL constrain a conversation to the first-version business lifecycle values.

#### Scenario: Supported conversation status is persisted
- **WHEN** a conversation is inserted or updated
- **THEN** its status SHALL be one of `ACTIVE`, `ARCHIVED`, or `DELETED`

#### Scenario: New conversation receives the active default
- **WHEN** a conversation is inserted without an explicit status
- **THEN** PostgreSQL SHALL persist its status as `ACTIVE`

### Requirement: Message persistence schema
The system SHALL persist user-visible Chat messages in a `messages` table without a message lifecycle status.

#### Scenario: Message table columns are defined
- **WHEN** the Chat persistence migration is applied
- **THEN** `messages.id` SHALL be a `BIGINT` primary key without a database identity or server-generated default
- **AND** `messages.conversation_id` SHALL be `BIGINT NOT NULL`
- **AND** `messages.parent_message_id` SHALL be nullable `BIGINT`
- **AND** `messages.role` SHALL be `VARCHAR(32) NOT NULL`
- **AND** `messages.content` SHALL be `TEXT NOT NULL`
- **AND** `messages.transformed_content` SHALL be nullable `TEXT`
- **AND** `messages.token_count` SHALL be nullable `INTEGER`
- **AND** `messages.model_name` SHALL be nullable `VARCHAR(255)`
- **AND** `messages.rag_references` SHALL be `JSONB NOT NULL DEFAULT '[]'::jsonb`
- **AND** `messages.metadata` SHALL be `JSONB NOT NULL DEFAULT '{}'::jsonb`
- **AND** `messages.created_at` and `messages.updated_at` SHALL be timezone-aware timestamps with current-time server defaults
- **AND** the table MUST NOT contain a `status` column

#### Scenario: Optional enrichment fields remain empty
- **WHEN** a message is persisted before model attribution or token accounting semantics are implemented
- **THEN** `token_count` and `model_name` SHALL accept `NULL`

### Requirement: Message role constraint
The system SHALL persist only user and assistant roles in the business message table.

#### Scenario: Supported message role is persisted
- **WHEN** a business message is inserted or updated
- **THEN** its role SHALL be either `USER` or `ASSISTANT`

#### Scenario: Runtime-only role is rejected
- **WHEN** a message uses `SYSTEM`, `TOOL`, or another unsupported runtime role
- **THEN** the database SHALL reject the row

### Requirement: Conversation and message referential integrity
The system SHALL enforce conversation ownership and same-conversation parent relationships for messages.

#### Scenario: Message belongs to an existing conversation
- **WHEN** a message is inserted
- **THEN** `messages.conversation_id` SHALL reference an existing `conversations.id`

#### Scenario: Root message has no parent
- **WHEN** a root message is inserted
- **THEN** `parent_message_id` SHALL accept `NULL`

#### Scenario: Child message references a parent in the same conversation
- **WHEN** a message is inserted with a non-null `parent_message_id`
- **THEN** the pair `(conversation_id, parent_message_id)` SHALL reference `(conversation_id, id)` of an existing message

#### Scenario: Cross-conversation parent is rejected
- **WHEN** a message references the ID of a message belonging to another conversation
- **THEN** the database SHALL reject the row

#### Scenario: Hard-deleted conversation removes owned messages
- **WHEN** a conversation row is physically deleted
- **THEN** its messages SHALL be deleted through the conversation foreign key cascade

### Requirement: Chat JSON extension containers
The system SHALL provide non-null JSONB containers for RAG references and message metadata without fixing a RAG reference element schema in this change.

#### Scenario: JSON containers receive defaults
- **WHEN** a message is inserted without `rag_references` or `metadata`
- **THEN** `rag_references` SHALL be persisted as an empty JSON array
- **AND** `metadata` SHALL be persisted as an empty JSON object

#### Scenario: ORM maps the reserved metadata column
- **WHEN** the SQLAlchemy Message model is inspected
- **THEN** its Python attribute SHALL be named `metadata_`
- **AND** the mapped PostgreSQL column SHALL remain named `metadata`

### Requirement: Chat persistence indexes and stable ordering
The system SHALL provide indexes that support conversation listing, deterministic message history loading, and answer-branch lookup.

#### Scenario: Conversation listing index is present
- **WHEN** the Chat migration indexes are inspected
- **THEN** an index SHALL cover `conversations(user_id, status, updated_at DESC, id DESC)`

#### Scenario: Message history index is present
- **WHEN** the Chat migration indexes are inspected
- **THEN** an index SHALL cover `messages(conversation_id, created_at, id)`
- **AND** consumers SHALL be able to order a conversation history by `(created_at ASC, id ASC)`

#### Scenario: Parent branch index is present
- **WHEN** the Chat migration indexes are inspected
- **THEN** an index SHALL cover `messages(conversation_id, parent_message_id)`

### Requirement: Chat ORM migration visibility
The system SHALL expose Chat mapped models to the shared SQLAlchemy metadata used by Alembic.

#### Scenario: Alembic loads Chat tables
- **WHEN** Alembic initializes `target_metadata`
- **THEN** the Chat models SHALL be imported before migration comparison
- **AND** `conversations` and `messages` SHALL be present in the metadata

### Requirement: Reversible Chat schema migration
The system SHALL provide a reversible Alembic migration for the Chat persistence tables.

#### Scenario: Upgrade creates tables in dependency order
- **WHEN** the migration upgrade runs
- **THEN** it SHALL create `conversations` before `messages`

#### Scenario: Downgrade removes tables in reverse dependency order
- **WHEN** the migration downgrade runs
- **THEN** it SHALL remove `messages` before `conversations`
