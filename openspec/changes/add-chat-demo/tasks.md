## 1. Tests And Dependencies

- [ ] 1.1 Add backend dependency entries for the minimal LangChain OpenAI-compatible chat integration.
- [ ] 1.2 Add failing tests for `POST /api/v1/chat` route mounting and successful response shape using a mocked LLM call.
- [ ] 1.3 Add failing tests for blank `message`, missing `OPENAI_API_KEY`, provider failure, and empty provider response.

## 2. Chat Module

- [ ] 2.1 Create `backend/app/modules/chat/` with module package, request/response schemas, service, and router files.
- [ ] 2.2 Implement request validation so empty or whitespace-only `message` returns HTTP 400 before any provider call.
- [ ] 2.3 Implement the service path that reads `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, and optional `OPENAI_MODEL`, defaulting the model to `gpt-4o-mini`.
- [ ] 2.4 Implement the LangChain `ChatOpenAI` single-turn call and return the answer text.
- [ ] 2.5 Normalize missing API key to HTTP 503 and provider/empty-response failures to HTTP 502 application errors.

## 3. Routing And Verification

- [ ] 3.1 Include the chat router in `backend/app/api/v1/router.py` at `POST /api/v1/chat` without touching placeholder auth, users, or orders behavior.
- [ ] 3.2 Run the focused chat tests and then the full backend test suite.
- [ ] 3.3 Verify the ASGI app still imports and health checks remain independent from LLM configuration.
