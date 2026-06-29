## Context

The backend currently has a minimal FastAPI structure with versioned routing, a shared `APIResponse` envelope, and placeholder modules created during initialization. The auth, users, and orders modules are not part of this change and are treated as unrelated placeholders.

The first RAG-related step is a pure chat demo: prove that the backend can receive a message, call an OpenAI-compatible chat model through LangChain, and return the answer. The demo must stay small enough to build and verify before adding retrieval, memory, document ingestion, or user isolation.

## Goals / Non-Goals

**Goals:**

- Add one anonymous single-turn chat endpoint at `POST /api/v1/chat`.
- Accept one `message` string and return one `answer` string in the existing `APIResponse` envelope.
- Use `langchain-openai` and its OpenAI-compatible chat model integration.
- Read provider configuration from `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, and optional `OPENAI_MODEL` in `backend/.env` or the process environment.
- Keep application startup independent from LLM configuration; missing `OPENAI_API_KEY` is reported when the chat endpoint is called.
- Add tests that exercise the LangChain integration path with test-local mocks so default pytest runs do not depend on network, provider quota, or real `.env` secrets.

**Non-Goals:**

- No authentication or user-specific behavior.
- No multi-turn message history or server-side conversation state.
- No streaming response.
- No database persistence.
- No RAG retrieval, embeddings, vector store, document parsing, or prompt-grounding workflow.
- No frontend chat UI.
- No redesign of placeholder `auth`, `users`, or `orders` modules.

## Decisions

1. **Use a minimal `chat` module instead of extending existing placeholder modules.**

   The feature will live under `backend/app/modules/chat/` with router, schemas, and service files that match the existing module layout. This keeps the demo isolated and avoids implying that auth, users, or orders are designed dependencies.

   Alternative considered: adding the endpoint directly in `api/v1/router.py`. That would be faster for a spike, but it would break the module boundary that the project skeleton already established.

2. **Expose a single endpoint at `POST /api/v1/chat`.**

   The endpoint path is singular because this demo does not create or list chat resources. It accepts a single message and returns one answer.

   Alternative considered: `POST /api/v1/chat/completions`, mirroring provider APIs. That is unnecessary for the application API and leaks provider vocabulary into the domain route.

3. **Use `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL` directly.**

   The OpenAI-compatible ecosystem already commonly uses these names, and compatible APIs can reuse `OPENAI_API_KEY` with their own `OPENAI_BASE_URL`. The implementation should extend the existing `Settings` object with alias-based fields for these exact names so values in `backend/.env` are available without requiring shell-level exports. `OPENAI_MODEL` defaults to `gpt-4o-mini` so local development only needs a key for the default OpenAI path, or key/base URL/model for compatible providers.

   Alternative considered: prefixing settings with `KE_ENGINE_`. That would align with existing application settings but adds extra mapping for common OpenAI-compatible tooling.

4. **Fail at request time when LLM configuration is missing.**

   Application startup must remain usable without LLM credentials. If `OPENAI_API_KEY` is missing, the chat endpoint returns a 503 application error with a clear message. This lets health checks and unrelated endpoints continue to run.

   Alternative considered: failing startup. That is stricter but makes the demo less ergonomic and couples all backend startup to an optional external integration.

5. **Use test-local LLM mocks for default chat success testing.**

   The production service should still instantiate the real LangChain/OpenAI-compatible client from runtime configuration. Default tests should patch that client inside the test process, not in application code, so they verify request/response behavior and service wiring without depending on network access, provider quota, or secret-bearing `.env` files.

   Alternative considered: calling a real configured provider in default pytest. That proves more end-to-end behavior, but it makes the normal test suite depend on external availability, cost, latency, and local credentials.

6. **Cache the demo chat model client, not the service object.**

   `ChatService` stays stateless and can be constructed per request. The LangChain `ChatOpenAI` client is cached behind a module-level factory for the demo so repeated chat requests do not recreate the provider wrapper. This is intentionally narrower than a full LLM abstraction; future AI/RAG chain work should extract provider management into a dedicated layer.

   Alternative considered: initializing the LLM during application startup. That would make missing LLM configuration affect unrelated endpoints, which conflicts with this demo's request-time configuration error behavior.

## Risks / Trade-offs

- OpenAI-compatible APIs may differ in model names or supported parameters -> keep provider settings limited to key, base URL, and model in this demo.
- LangChain dependency versions may change quickly -> use the smallest required dependency surface and avoid advanced chain abstractions in the first pass.
- The endpoint is anonymous -> acceptable for a local demo, but any future persisted chat or RAG content must add user boundaries before handling private data.
- Single-turn chat cannot demonstrate RAG quality -> intentional scope control; retrieval and grounding will be separate follow-up changes.
- Production LLM calls require valid credentials and network access -> keep missing-key behavior explicit, but avoid making default tests depend on real credentials.
- External provider failures can vary widely -> normalize missing key to 503 and upstream call failures to 502 with concise application errors that do not expose secrets.
- Error responses should use the shared `APIResponse` envelope with non-zero `code`, a concise `message`, and `data: null`.

## Migration Plan

This is an additive backend change. Deployment requires installing the new Python dependencies and setting provider variables in `backend/.env` or the process environment when real chat calls are needed.

Rollback is to remove the chat router inclusion and the `chat` module files, then remove the LangChain dependencies.

## Open Questions

None for the first demo scope.
