## Why

The project is intended to evolve toward RAG, but it first needs a minimal, runnable chat path that proves the backend can call an LLM through the LangChain ecosystem.

This change keeps the first step deliberately small: an anonymous, single-turn chat demo that does not depend on the placeholder auth, users, or orders modules.

## What Changes

- Add a new `chat` capability with one anonymous single-turn HTTP endpoint.
- Accept a single user message and return the model answer through the existing `APIResponse` envelope.
- Use LangChain's OpenAI-compatible chat integration so `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, and optional `OPENAI_MODEL` configure the provider.
- Return a clear runtime error from the chat endpoint when `OPENAI_API_KEY` is missing instead of failing application startup.
- Add focused tests for route mounting, request validation, missing configuration, and successful behavior through a real OpenAI-compatible LLM call using `.env` configuration.
- Do not add authentication, multi-turn memory, streaming responses, database persistence, RAG retrieval, embeddings, vector storage, or document ingestion in this change.

## Capabilities

### New Capabilities

- `chat-demo`: Anonymous single-turn chat demo backed by a LangChain OpenAI-compatible chat model.

### Modified Capabilities

- None.

## Impact

- Backend API: adds `POST /api/v1/chat`.
- Backend modules: adds `backend/app/modules/chat/`.
- Backend routing: includes the chat router in the versioned API router.
- Configuration: reads `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL` from `backend/.env` or the process environment.
- Dependencies: adds the minimal LangChain packages needed for OpenAI-compatible chat calls.
- Tests: adds focused backend tests for the new chat module and endpoint behavior.
