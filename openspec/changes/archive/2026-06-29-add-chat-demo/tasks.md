## 1. Tests And Dependencies

- [x] 1.1 Add backend dependency entries for the minimal LangChain OpenAI-compatible chat integration.
- [x] 1.2 Add failing tests for `POST /api/v1/chat` route mounting at the exact no-trailing-slash path.
- [x] 1.3 Add failing validation tests for blank `message`, missing `message`, and non-string `message`.
- [x] 1.4 Add failing configuration tests for missing and blank `OPENAI_API_KEY` while confirming app startup and health checks still work.
- [x] 1.5 Add a failing successful chat test that uses a test-local mock of the LangChain chat client and asserts a non-empty `data.answer`.
- [x] 1.6 Add a failing provider-failure test using intentionally invalid provider configuration and assert HTTP 502 without leaking secret values.

## 2. Chat Module

- [x] 2.1 Create `backend/app/modules/chat/` with module package, request/response schemas, service, and router files.
- [x] 2.2 Implement request validation so empty or whitespace-only `message` returns HTTP 400 before any provider call.
- [x] 2.3 Extend application settings so `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, and optional `OPENAI_MODEL` can be read from `backend/.env` or the process environment without requiring `KE_ENGINE_` prefixes.
- [x] 2.4 Implement the service path that treats missing, empty, or whitespace-only `OPENAI_API_KEY` as unconfigured and defaults missing or blank `OPENAI_MODEL` to `gpt-4o-mini`.
- [x] 2.5 Implement the real LangChain `ChatOpenAI` single-turn call and return the answer text.
- [x] 2.6 Normalize missing API key to HTTP 503 and provider failures to HTTP 502 application errors that do not expose secrets.
- [x] 2.7 Cache the demo `ChatOpenAI` client behind a module-level factory without turning `ChatService` into a singleton.

## 3. Routing And Verification

- [x] 3.1 Include the chat router in `backend/app/api/v1/router.py` at `POST /api/v1/chat` without touching placeholder auth, users, or orders behavior.
- [x] 3.2 Run the focused chat tests with test-local LLM mocks and then the full backend test suite.
- [x] 3.3 Verify the ASGI app still imports and health checks remain independent from LLM configuration.
