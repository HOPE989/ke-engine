## 1. Migration Contract

- [x] 1.1 RED: add `backend/tests/test_chat_migration.py` that loads the new Alembic revision and asserts the exact `conversations` and `messages` columns, Snowflake-compatible BIGINT primary keys, server defaults, status/role checks, JSONB defaults, foreign keys, same-conversation parent constraint, indexes, upgrade order, and reverse downgrade order.
- [x] 1.2 RED: run `uv run --extra dev pytest tests/test_chat_migration.py -q` from `backend/` and confirm it fails because the Chat migration does not exist.
- [x] 1.3 GREEN: add the Alembic revision after `202607080001` that creates `conversations` before `messages`, applies all specified constraints and indexes, and drops the tables in reverse dependency order.
- [x] 1.4 GREEN: rerun `uv run --extra dev pytest tests/test_chat_migration.py -q` and confirm the migration contract passes.

## 2. Chat ORM Models

- [x] 2.1 RED: add `backend/tests/test_chat_persistence.py` covering Conversation and Message table names, exact columns and nullability, enum values, server/application defaults, timezone-aware timestamps, JSONB mappings, `metadata_` to `metadata` mapping, foreign keys, unique/check constraints, and composite indexes.
- [x] 2.2 RED: run `uv run --extra dev pytest tests/test_chat_persistence.py -q` and confirm it fails because the Chat persistence models do not exist.
- [x] 2.3 GREEN: create the `backend/app/domains/chat/shared/` package and implement `ConversationStatus`, `MessageRole`, `Conversation`, and `Message` SQLAlchemy mappings using application-generated BIGINT IDs and the agreed two-table schema.
- [x] 2.4 GREEN: rerun `uv run --extra dev pytest tests/test_chat_persistence.py -q` and confirm the ORM contract passes.

## 3. Alembic Metadata Visibility

- [x] 3.1 RED: add a focused test proving Alembic initialization imports the Chat models and exposes `conversations` and `messages` through `Base.metadata`.
- [x] 3.2 GREEN: update `backend/alembic/env.py` to import the Chat models before assigning `target_metadata`, then rerun the focused test.

## 4. Constraint Behavior Verification

- [x] 4.1 Add PostgreSQL-backed integration coverage, guarded by a Chat test database environment variable, for JSONB defaults, a valid parent chain, rejection of a cross-conversation parent, rejection of unsupported conversation/message enum values, and cascade deletion of messages after a physical conversation delete.
- [x] 4.2 Run the integration coverage when PostgreSQL is configured and confirm the actual database behavior matches the migration and ORM contracts.

## 5. Final Verification

- [x] 5.1 Run the focused Chat suite: `uv run --extra dev pytest tests/test_chat_migration.py tests/test_chat_persistence.py -q`.
- [x] 5.2 Run the full backend suite: `uv run --extra dev pytest -q`.
- [x] 5.3 If the configured development database is available, verify a clean Alembic upgrade to head and downgrade back to `202607080001`.
- [x] 5.4 Run `openspec validate add-chat-conversation-persistence --strict` and confirm the change passes strict validation.
