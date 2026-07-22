# Chat Streaming Completion

## Purpose

Define the application-owned SSE protocol, persistence boundary, failure behavior, and subscriber lifecycle for Chat completions.
## Requirements
### Requirement: Completion responses use a stable SSE contract
The system SHALL return Chat completion output as Server-Sent Events projected into application-owned event types.

#### Scenario: Response is configured for streaming
- **WHEN** a valid completion request is accepted
- **THEN** the response SHALL use `text/event-stream`
- **AND** it SHALL disable HTTP caching and reverse-proxy response buffering

#### Scenario: LangGraph events are adapted rather than exposed
- **WHEN** the Graph produces `astream_events()` output
- **THEN** the SSE adapter SHALL project relevant output into the public Chat event schema
- **AND** it MUST NOT expose LangGraph's internal event object as the public protocol

### Requirement: Metadata is the first SSE event
The system SHALL emit an application-produced `metadata` event before any model content event.

#### Scenario: New conversation metadata is available in the first event
- **WHEN** a first-message completion starts successfully
- **THEN** the first SSE event SHALL be `metadata`
- **AND** its data SHALL contain the new `conversation_id` and persisted `user_message_id`

#### Scenario: Metadata follows durable user input
- **WHEN** the `metadata` event is emitted
- **THEN** the conversation when newly created and the USER message SHALL already be committed in one business transaction
- **AND** Graph execution SHALL not have started before that commit succeeds

### Requirement: Model output is streamed as content deltas
The system SHALL emit model text produced during Graph execution as ordered `content_delta` events.

#### Scenario: Text chunks preserve Graph emission order
- **WHEN** the LLM node emits message stream chunks
- **THEN** the adapter SHALL emit their text as `content_delta` events in the same order

#### Scenario: Non-public runtime events are ignored
- **WHEN** `astream_events()` emits lifecycle or diagnostic events that are not part of the public Chat schema
- **THEN** the adapter SHALL not forward those events to the client

### Requirement: Successful completion is confirmed after assistant persistence
The system SHALL use a `completed` event as the durable terminal boundary for both an ordinary answer and an intentional clarification interrupt.

#### Scenario: Ordinary assistant message is saved before completed
- **WHEN** the Graph reaches `END` with a complete assistant answer
- **THEN** the system SHALL persist one ASSISTANT business message linked to the submitted USER message
- **AND** it SHALL emit `completed` only after that transaction commits
- **AND** the event SHALL include `assistant_message_id` and `finish_reason` equal to `stop`

#### Scenario: Clarification question is saved before interrupted completion
- **WHEN** the Graph suspends with a clarification interrupt
- **THEN** the system SHALL persist the clarification question as one ASSISTANT business message linked to the submitted USER message
- **AND** it SHALL emit that question as ordered `content_delta` output
- **AND** it SHALL emit `completed` only after the ASSISTANT transaction commits
- **AND** the event SHALL include `assistant_message_id` and `finish_reason` equal to `interrupt`
- **AND** the LangGraph thread SHALL remain resumable

#### Scenario: Completed is the only success terminal event
- **WHEN** `completed` has been emitted with `finish_reason` equal to `stop` or `interrupt`
- **THEN** the stream SHALL end without emitting `error`

### Requirement: Failed completion discards the partial assistant answer
The system SHALL terminate an unsuccessful completion with an `error` event and SHALL NOT persist an incomplete ASSISTANT business message.

#### Scenario: LLM node fails after emitting partial tokens
- **WHEN** the LLM node raises an exception after one or more content deltas were emitted
- **THEN** the system SHALL preserve the committed USER message
- **AND** it SHALL discard the partial assistant content from the business message table
- **AND** it SHALL emit `error`
- **AND** it MUST NOT emit `completed`

#### Scenario: Assistant persistence fails
- **WHEN** Graph execution succeeds but the ASSISTANT business transaction fails
- **THEN** the system SHALL emit `error`
- **AND** it MUST NOT emit `completed`

### Requirement: Browser disconnect does not cancel Graph execution
The system SHALL treat an ordinary SSE subscriber disconnect as a transport event rather than a user-requested stop.

#### Scenario: Producer continues after subscriber disconnect
- **WHEN** the browser disconnects while the Graph is running
- **THEN** the SSE subscriber SHALL detach without cancelling the Graph producer
- **AND** the producer SHALL continue consuming Graph events
- **AND** a successfully completed answer SHALL still be persisted as an ASSISTANT business message

#### Scenario: Detached subscriber does not accumulate delivery events
- **WHEN** no subscriber remains for a running producer
- **THEN** the producer SHALL stop enqueueing SSE events for that subscriber
- **AND** it SHALL retain only the data needed to assemble and persist the final answer

### Requirement: First-version SSE has no replay or heartbeat protocol
The system SHALL provide a live completion stream without durable per-token delivery state.

#### Scenario: Reconnected client does not request token replay
- **WHEN** a client reconnects after losing a completion stream
- **THEN** the API MUST NOT claim support for `Last-Event-ID` or replay of prior content deltas
- **AND** the client SHALL use persisted message history to observe only successfully completed assistant messages

#### Scenario: Stream contains no heartbeat event
- **WHEN** a completion remains in progress without a model delta
- **THEN** the server SHALL not emit an application heartbeat event in this version

### Requirement: Completion requests are not automatically retried
The first-version completion contract SHALL assume serialized sends per conversation and MUST NOT rely on request idempotency.

#### Scenario: Transport failure is not retried automatically
- **WHEN** a client cannot determine whether a completion POST was accepted
- **THEN** the client MUST NOT automatically repeat the request with the same content

#### Scenario: One client serializes sends within a conversation
- **WHEN** a completion for a conversation remains active
- **THEN** the client SHALL not start a second completion for that conversation

### Requirement: Intentional clarification is not a runtime failure
The SSE adapter SHALL distinguish a LangGraph clarification interrupt from an exception or failed node attempt.

#### Scenario: Interrupt event is adapted
- **WHEN** Graph streaming reports the supported Business Understanding interrupt payload
- **THEN** the adapter SHALL extract the clarification question
- **AND** it MUST NOT expose LangGraph's internal interrupt object as the public SSE payload
- **AND** it MUST NOT emit `error`

#### Scenario: Unsupported interrupt payload fails safely
- **WHEN** Graph streaming reports an interrupt payload that does not satisfy the clarification schema
- **THEN** the completion SHALL emit `error`
- **AND** it MUST NOT persist an incomplete ASSISTANT clarification message
