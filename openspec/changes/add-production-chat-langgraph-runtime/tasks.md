## 1. Runtime dependencies and contracts

- [ ] 1.1 Add the compatible LangGraph PostgreSQL saver, psycopg async pool, and Chat model dependencies to the backend environment and lockfile
- [ ] 1.2 Add startup validation for the server-controlled `OPENAI_MODEL` while continuing to reuse `DATABASE_URL`
- [ ] 1.3 Define HTTP request/response contracts for conversation pages, message-history pages, and completion input with string-encoded identifiers
- [ ] 1.4 Define typed SSE payload contracts for `metadata`, `content_delta`, `completed`, and `error`

## 2. LangGraph infrastructure and minimal graph

- [ ] 2.1 Add failing unit tests for `MessagesState` merging, the exact `START -> llm -> END` topology, runtime model injection, and absence of node retry
- [ ] 2.2 Implement Chat state, the injected-model `llm` node, and a builder that returns the uncompiled minimal Graph
- [ ] 2.3 Add failing PostgreSQL integration tests for saver setup, two-turn context on one thread, and isolation between conversation thread IDs
- [ ] 2.4 Implement safe `DATABASE_URL` conversion, the dedicated psycopg pool, `AsyncPostgresSaver` setup, and resource shutdown
- [ ] 2.5 Add the Chat API lifespan resource container that initializes the model and saver before compiling the production Graph
- [ ] 2.6 Verify startup fails on model or saver initialization errors and never falls back to an in-memory checkpointer

## 3. Conversation persistence use cases

- [ ] 3.1 Add failing repository tests for current-user ownership, 404 concealment, stable cursor pagination, and deterministic message ordering
- [ ] 3.2 Implement conversation and message repositories using the existing SQLAlchemy models without accessing LangGraph internal tables
- [ ] 3.3 Add failing service tests for first-message conversation creation, title derivation, existing-conversation append, activity updates, and blank-content rejection
- [ ] 3.4 Implement the transactional conversation service that persists the conversation when needed and its USER message before Graph execution
- [ ] 3.5 Implement authenticated conversation-list and message-history routes with decimal-string ID serialization

## 4. Streaming completion runtime

- [ ] 4.1 Add failing SSE adapter tests for metadata-first ordering, `astream_events()` content projection, ignored runtime events, and public payload serialization
- [ ] 4.2 Implement the application-owned SSE adapter and streaming response headers without heartbeat or replay behavior
- [ ] 4.3 Add failing producer tests for ASSISTANT persistence before `completed`, mutually exclusive terminal events, and partial-answer discard on Graph or database failure
- [ ] 4.4 Implement the managed completion producer that consumes Graph events, assembles the answer, persists the ASSISTANT message, and emits the terminal event
- [ ] 4.5 Add failing disconnect tests proving subscriber detachment does not cancel Graph execution or accumulate unused delivery events
- [ ] 4.6 Implement subscriber/producer decoupling and application shutdown handling for in-flight producer tasks
- [ ] 4.7 Implement `POST /api/v1/chat/completions`, including ownership checks, metadata-first streaming, conversation thread configuration, and no request-level model override

## 5. End-to-end verification and handoff

- [ ] 5.1 Add API tests for new and existing conversations, string IDs, successful histories, unauthorized 404 responses, error termination, and client-disconnect persistence
- [ ] 5.2 Add a process/node failure integration case confirming the USER message remains while no partial ASSISTANT business message becomes durable
- [ ] 5.3 Run the full backend unit and PostgreSQL integration test suites and resolve all regressions
- [ ] 5.4 Run strict OpenSpec validation, document the Chat API startup command and environment requirements, and confirm active stop, archive, concurrency, idempotency, heartbeat, and replay remain out of scope
