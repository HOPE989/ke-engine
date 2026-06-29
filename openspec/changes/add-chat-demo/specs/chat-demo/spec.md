## ADDED Requirements

### Requirement: Anonymous single-turn chat endpoint

The system SHALL expose an anonymous single-turn chat endpoint at `POST /api/v1/chat` without requiring a trailing slash.

#### Scenario: Successful chat request

- **WHEN** a client sends `POST /api/v1/chat` with a non-empty JSON `message`
- **THEN** the system SHALL call the configured LangChain OpenAI-compatible chat model with that message
- **AND** the system SHALL return HTTP 200 with an `APIResponse` payload whose `data.answer` is the model response text

#### Scenario: Chat endpoint path has no trailing slash

- **WHEN** a client sends `POST /api/v1/chat` with a non-empty JSON `message`
- **THEN** the system SHALL process the request at exactly `/api/v1/chat`

#### Scenario: Endpoint does not require authentication

- **WHEN** a client sends `POST /api/v1/chat` without authentication headers
- **THEN** the system SHALL process the request according to the chat request rules

### Requirement: Chat request validation

The system SHALL reject invalid chat requests before calling the LLM provider.

#### Scenario: Blank message is rejected

- **WHEN** a client sends `POST /api/v1/chat` with a `message` that is empty or only whitespace
- **THEN** the system SHALL return HTTP 400 with an application error explaining that `message` is required
- **AND** the system MUST NOT call the LLM provider

#### Scenario: Missing message is rejected

- **WHEN** a client sends `POST /api/v1/chat` without a `message` field
- **THEN** the system SHALL return HTTP 422 with a request validation error
- **AND** the system MUST NOT call the LLM provider

#### Scenario: Non-string message is rejected

- **WHEN** a client sends `POST /api/v1/chat` with a `message` value that is not a string
- **THEN** the system SHALL return HTTP 422 with a request validation error
- **AND** the system MUST NOT call the LLM provider

### Requirement: OpenAI-compatible provider configuration

The system SHALL configure the chat model from OpenAI-compatible variables in `backend/.env` or the process environment.

#### Scenario: Real provider configuration is present

- **WHEN** `OPENAI_API_KEY` is configured and a client sends a valid chat request
- **THEN** the system SHALL perform a real LangChain OpenAI-compatible chat model call
- **AND** the system SHALL return HTTP 200 with a non-empty `data.answer`

#### Scenario: Required API key is missing

- **WHEN** a client sends a valid chat request and `OPENAI_API_KEY` is not configured
- **THEN** the system SHALL return HTTP 503 with an application error explaining that `OPENAI_API_KEY` is required
- **AND** the application MUST remain startable without `OPENAI_API_KEY`

#### Scenario: Required API key is blank

- **WHEN** a client sends a valid chat request and `OPENAI_API_KEY` is empty or only whitespace
- **THEN** the system SHALL treat `OPENAI_API_KEY` as not configured
- **AND** the system SHALL return HTTP 503 with an application error explaining that `OPENAI_API_KEY` is required

#### Scenario: Compatible base URL is configured

- **WHEN** `OPENAI_BASE_URL` is configured and a valid chat request is processed
- **THEN** the system SHALL configure the LangChain chat model to use that base URL

#### Scenario: Model name is omitted

- **WHEN** `OPENAI_MODEL` is not configured and a valid chat request is processed
- **THEN** the system SHALL use `gpt-4o-mini` as the default model name

#### Scenario: Model name is blank

- **WHEN** `OPENAI_MODEL` is empty or only whitespace and a valid chat request is processed
- **THEN** the system SHALL use `gpt-4o-mini` as the default model name

### Requirement: Provider error handling

The system SHALL normalize LLM provider failures into application errors.

#### Scenario: Provider call fails

- **WHEN** the configured LangChain chat model raises an error while processing a valid chat request
- **THEN** the system SHALL return HTTP 502 with an application error explaining that the chat provider request failed
- **AND** the error response MUST NOT include `OPENAI_API_KEY` or other secret values
