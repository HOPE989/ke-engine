## Context

Chat API currently compiles the only production Graph during FastAPI lifespan, injects `BaseChatModel` through `ChatRuntimeContext`, persists checkpoints with PostgreSQL, and executes each accepted turn in `CompletionProducer`. The Graph topology already uses typed `Command(goto)` routing. Existing 18 business-understanding cases validate the deterministic scorer with oracle outputs but do not invoke a live model.

Langfuse is an external observability service and must never become a business dependency. Studio is a developer-only surface and must not force Agent Server to recreate the production database, Redis lock, Registry, SSE, or checkpointer lifecycle.

## Goals / Non-Goals

**Goals:**

- Trace a complete accepted Chat turn as one Langfuse root observation with nested LangGraph/LangChain activity.
- Preserve complete raw messages, Prompt and model/structured output for internal debugging.
- Keep tracing fail-open and preserve every existing business error and terminal event.
- Expose the existing Graph to Studio with only a development model binding.
- Run the current 18 labeled cases as a visible Langfuse Dataset Experiment with five deterministic scores.

**Non-Goals:**

- A generic observability provider abstraction or parallel LangSmith tracing layer.
- Prompt Management, sampling, masking, LLM-as-a-Judge, CI quality gates, model matrices, or online evaluation.
- Reusing the full FastAPI lifespan in Agent Server.
- Changing HTTP/SSE contracts, Redis locking, database schemas, checkpoint semantics, Graph node names, edges, or routing.

## Decisions

### Use one concrete Langfuse resource pair

The infrastructure module creates one `LangfuseResources(client, handler)` from explicit Settings values. Missing or invalid configuration returns `None`; creation and shutdown exceptions are logged. No provider protocol, registry, or generic span abstraction is introduced.

The alternative of letting each caller instantiate `get_client()` from process environment is rejected because this project loads `backend/.env` through Pydantic without exporting values to `os.environ`, which could give the callback and application different configuration.

Langfuse 4.14.1 的官方 `CallbackHandler` 会导入 LangChain 元包，因此运行依赖显式包含兼容的 LangChain 1.3.x；仅安装 `langchain-core` 和 `langchain-openai` 不足以加载该 integration。

### Trace at the CompletionProducer boundary

`CompletionProducer.run()` encloses the existing metadata, Graph, ASSISTANT commit and terminal flow in one `chat-completion` root observation. The callback is added to that invocation's `RunnableConfig`; the title model and unrelated calls do not receive it. The root records session/user identity, raw turn input, final content, finish reason and completed/error status.

A narrow context manager isolates Langfuse enter/exit failures while explicitly re-raising any business exception. Trace updates are best-effort. The SDK's asynchronous exporter handles delivery; shutdown is moved to a worker thread so FastAPI cleanup does not block the event loop.

### Keep one Graph topology and add an optional bound model

The builder accepts `bound_model=None`. The default production path continues to declare `ChatRuntimeContext` and register the existing runtime-aware nodes. Bound mode registers partials of shared model-explicit node cores and omits the non-serializable model context schema. All node names and edges remain in the same builder.

The Studio adapter only loads Settings, creates the Chat model and optional callback, calls the bound builder and returns a compiled graph. A copied Studio topology and the full FastAPI lifespan are rejected because both would drift or create unused production resources.

### Use a Langfuse-hosted Dataset for the first Experiment

The repository fixture remains the source of truth. Stable project-level item IDs allow idempotent upsert into `ke-engine/business-understanding-v1`. A hosted Dataset is chosen over local experiment data because it creates a Dataset Run and enables UI comparison.

The task calls the real current business-understanding node with the configured model. The evaluator reconstructs the existing `EvaluationCase`, calls the current scorer once, and maps its five numerator/denominator pairs to numeric Scores. Concurrency is fixed to one. The explicit CLI authenticates and fails non-zero instead of silently skipping evaluation.

## Risks / Trade-offs

- [Raw content increases trace volume] → Accepted for this internal self-hosted deployment; infrastructure secrets and lock tokens are never added explicitly.
- [Langfuse SDK or callback failure could mask business behavior] → Isolate creation, update and context cleanup; add regression tests where tracing fails on every boundary.
- [Bound model mode could diverge from production nodes] → Both runtime and bound wrappers call the same model-explicit node core; the builder remains the only topology source.
- [Hosted Dataset can retain old items] → Stable v1 IDs upsert current cases; structural dataset changes use a new explicit Dataset version name rather than automatic deletion.
- [Structured-output failures do not produce a normal schema score] → Let the Experiment runner record the item task failure instead of fabricating a result.
- [Real model evaluation is nondeterministic and has cost] → Keep it an explicit serial developer command; default pytest remains fake/offline.

## Migration Plan

1. Add dependencies and optional Langfuse Settings fields.
2. Deploy with no Langfuse credentials to verify the unchanged no-tracing path.
3. Configure self-hosted Langfuse credentials and observe Chat traces.
4. Use Studio and Experiment commands only in development.

Rollback removes the Langfuse resource wiring, Studio adapter and evaluation package; no database or external protocol migration is required. Existing Langfuse traces and Dataset Runs may remain as historical data.

## Open Questions

No blocking questions. Prompt Management, judges, thresholds and CI gates will be decided only after reviewing the first live Dataset Run.
