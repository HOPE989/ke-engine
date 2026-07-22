## MODIFIED Requirements

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

## ADDED Requirements

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
