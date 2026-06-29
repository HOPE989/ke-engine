# Chat Demo Design

## Goal

Add the smallest useful backend chat demo before building RAG. The demo proves that the FastAPI backend can accept one user message, call an OpenAI-compatible chat model through LangChain, and return one answer.

This design intentionally treats the existing `auth`, `users`, and `orders` modules as initialization placeholders. The chat demo does not depend on them.

## Scope

In scope:

- Anonymous `POST /api/v1/chat` endpoint.
- Single-turn request with one `message` field.
- Success response wrapped in the existing `APIResponse` shape.
- LangChain OpenAI-compatible chat call through `langchain-openai`.
- Runtime provider configuration from `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, and optional `OPENAI_MODEL`.
- Clear endpoint errors for missing API key, upstream provider failure, and empty model response.
- Tests that avoid real LLM network calls.

Out of scope:

- Authentication and user identity.
- Multi-turn conversation history.
- Server-side memory or database persistence.
- Streaming responses.
- RAG retrieval, embeddings, vector storage, document parsing, or prompt grounding.
- Frontend chat UI.
- Redesigning placeholder modules.

## API Contract

Endpoint:

```text
POST /api/v1/chat
```

Request:

```json
{
  "message": "你好"
}
```

Success response:

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "answer": "..."
  }
}
```

Error behavior:

- Empty or whitespace-only `message`: HTTP 400 application error.
- Missing `message`: request validation error.
- Missing `OPENAI_API_KEY`: HTTP 503 application error.
- Provider call failure: HTTP 502 application error.
- Empty provider answer: HTTP 502 application error.

## Architecture

The implementation keeps the current module style and adds a single isolated feature module:

```text
backend/app/modules/chat/
  __init__.py
  schemas.py
  service.py
  router.py
```

Request flow:

```text
POST /api/v1/chat
  -> chat.router
  -> ChatService
  -> langchain-openai ChatOpenAI
  -> APIResponse[{ answer }]
```

The versioned API router includes the chat router at `/chat`. The route handler validates blank messages before calling the service. The service reads OpenAI-compatible environment variables at call time so application startup and health checks still work without LLM credentials.

## Configuration

The demo uses the common OpenAI-compatible environment names directly:

```text
OPENAI_API_KEY   required for calls
OPENAI_BASE_URL  optional compatible API base URL
OPENAI_MODEL     optional model name, default gpt-4o-mini
```

No `KE_ENGINE_` mapping is added for this first demo. Compatible providers can be used by setting `OPENAI_BASE_URL` and `OPENAI_MODEL`.

## Testing

Tests should cover:

- The chat route is mounted at `POST /api/v1/chat`.
- A non-empty message returns the expected response envelope when the LLM call is mocked.
- Blank messages return HTTP 400 and do not call the provider.
- Missing `OPENAI_API_KEY` returns HTTP 503 from the endpoint, while app import and health checks still work.
- Provider exceptions and empty provider responses return HTTP 502.

Default tests must not require a real API key, external network call, or deterministic model output.

## OpenSpec

The matching OpenSpec change is `add-chat-demo`.

Artifacts:

- `openspec/changes/add-chat-demo/proposal.md`
- `openspec/changes/add-chat-demo/design.md`
- `openspec/changes/add-chat-demo/specs/chat-demo/spec.md`
- `openspec/changes/add-chat-demo/tasks.md`
