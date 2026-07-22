## Why

The current Chat Graph sends every request directly to a general LLM, so it cannot distinguish enterprise business questions, non-business conversation, or requests that need clarification before execution. ke-engine now needs a bounded Business Understanding entry point that preserves know-engine's proven flat intent-and-entity extraction pattern while replacing its `related` hard gate with recoverable LangGraph routing for the railway transportation and coal business scenario.

## What Changes

- Add a structured Business Understanding result with `route`, flat business `intent`, railway/coal business `entities`, concise `reasoning`, and an optional `clarification_question`.
- Route every Chat request to exactly one of `BUSINESS`, `NON_BUSINESS`, or `CLARIFY` without introducing `BusinessDomain` or a `related` boolean.
- Make routing decisions inside the responsible Graph nodes with LangGraph `Command(update=..., goto=...)`, following the DeerFlow control pattern; fixed non-decision transitions remain static edges.
- Define the V1 business intents as `POLICY_RULE_QA`, `TRANSPORT_OPERATION_QA`, `COAL_SALES_QA`, `PROFESSIONAL_KNOWLEDGE_QA`, `BUSINESS_DATA_QUERY`, and `OTHER_BUSINESS`.
- Keep NON_BUSINESS requests on the existing general-model answer path.
- Suspend CLARIFY requests with LangGraph interrupt, persist and stream one clarification question, then resume the same checkpoint when the user supplies the next message.
- Serialize the complete lifecycle of each conversation completion with one coarse Redis distributed lock so concurrent requests cannot race the same LangGraph thread.
- Terminate BUSINESS requests at an explicit business boundary in this change; RAG, SQL execution, and grounded business answering remain out of scope.
- Add deterministic graph tests and a railway/coal intent evaluation dataset covering single-turn routing, multi-turn ellipsis, boundary negatives, clarification, entity extraction, and schema validity.
- **BREAKING**: extend the Chat completion terminal contract so an intentional clarification interrupt can end the current HTTP completion without being reported as an error, while preserving the checkpoint for resume.

## Capabilities

### New Capabilities

- `business-understanding`: Structured railway/coal intent recognition, entity extraction, three-way routing, clarification rules, and evaluation behavior.

### Modified Capabilities

- `chat-langgraph-runtime`: Replace the single `START -> llm -> END` topology with a Business Understanding entry point, node-owned `Command(goto)` branches, and resumable clarification state.
- `chat-streaming-completion`: Define the public SSE and persistence behavior for an intentional clarification interrupt and its terminal event.
- `chat-conversation-api`: Define how the next owned-conversation completion resumes a pending clarification checkpoint while keeping the public input shape server-controlled.

## Impact

- Affected code: Chat Graph state, builder, nodes, runtime context, completion producer/service, SSE schemas, Chat API orchestration, and the existing Redis lock infrastructure.
- Affected prompts and tests: new Business Understanding Prompt, structured output models, intent evaluation cases, graph routing tests, and interrupt/resume integration tests.
- Persistence impact: no business-table migration is required; USER and ASSISTANT clarification messages continue to use the existing message schema, while resumable runtime state remains in the LangGraph PostgreSQL checkpointer.
- Deferred work: business RAG, SQL Tool execution, fine-grained plan/document/analysis intents, prompt-specific grounded answers, and production data-source integration.
