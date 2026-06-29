## 1. Tests And Dependencies

- [ ] 1.1 Add backend dependency entries for the minimal LangChain OpenAI-compatible chat integration.
- [ ] 1.2 Add failing tests for `POST /api/v1/chat` route mounting at the exact no-trailing-slash path.
- [ ] 1.3 Add failing validation tests for blank `message`, missing `message`, and non-string `message`.
- [ ] 1.4 Add failing configuration tests for missing and blank `OPENAI_API_KEY` while confirming app startup and health checks still work.
- [ ] 1.5 Add a failing successful chat test that uses the real OpenAI-compatible LLM configured by `backend/.env` and asserts a non-empty `data.answer`.
- [ ] 1.6 Add a failing provider-failure test using intentionally invalid provider configuration and assert HTTP 502 without leaking secret values.

## 2. Chat Module

- [ ] 2.1 Create `backend/app/modules/chat/` with module package, request/response schemas, service, and router files.
- [ ] 2.2 Implement request validation so empty or whitespace-only `message` returns HTTP 400 before any provider call.
- [ ] 2.3 Extend application settings so `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, and optional `OPENAI_MODEL` can be read from `backend/.env` or the process environment without requiring `KE_ENGINE_` prefixes.
- [ ] 2.4 Implement the service path that treats missing, empty, or whitespace-only `OPENAI_API_KEY` as unconfigured and defaults missing or blank `OPENAI_MODEL` to `gpt-4o-mini`.
- [ ] 2.5 Implement the real LangChain `ChatOpenAI` single-turn call and return the answer text.
- [ ] 2.6 Normalize missing API key to HTTP 503 and provider failures to HTTP 502 application errors that do not expose secrets.

## 3. Routing And Verification

- [ ] 3.1 Include the chat router in `backend/app/api/v1/router.py` at `POST /api/v1/chat` without touching placeholder auth, users, or orders behavior.
- [ ] 3.2 Run the focused chat tests with real `.env` LLM configuration and then the full backend test suite.
- [ ] 3.3 Verify the ASGI app still imports and health checks remain independent from LLM configuration.
