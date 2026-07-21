## Context

The production Chat runtime currently compiles a single `START -> llm -> END` LangGraph over `MessagesState`. The Chat model and PostgreSQL checkpointer are lifespan-managed, the business conversation ID is the checkpoint thread ID, USER messages are committed before Graph execution, ASSISTANT messages are committed before the terminal SSE event, and browser disconnect does not cancel the producer.

know-engine provides the functional reference for one-call intent recognition, entity extraction, conversation-aware classification, and intent-to-Prompt mapping. ke-engine will migrate that pattern to railway transportation, coal transportation, coal sales, enterprise regulations, and business-data questions. It will not copy know-engine's automotive labels, `related` hard gate, or centralized Java application-service topology.

This change crosses Graph state and topology, structured model invocation, checkpoint interruption, completion orchestration, SSE adaptation, and business-message persistence. It therefore needs an explicit end-to-end design before implementation.

## Goals / Non-Goals

**Goals:**

- Introduce one structured Business Understanding entry node using the existing injected Chat model.
- Replace binary domain gating with `BUSINESS`, `NON_BUSINESS`, and `CLARIFY` Graph routes.
- Preserve a small flat business-intent taxonomy whose values can later select professional answer Prompts.
- Extract a bounded set of railway and coal entities without introducing a separate domain ontology.
- Keep NON_BUSINESS on the existing general-answer path.
- Make CLARIFY a real LangGraph interrupt that persists a user-visible question and resumes from the same conversation checkpoint.
- Provide an explicit, deterministic BUSINESS boundary while RAG and SQL are not yet implemented.
- Preserve existing ownership, commit-before-execute, checkpoint, disconnect, and failure consistency rules.

**Non-Goals:**

- Implement business RAG, RAG MCP calls, SQL Tool execution, grounded business answers, citations, or evidence validation.
- Integrate all ADS tables or build a complete railway ontology.
- Split plan, freight-document, analysis, and exception handling into separate V1 intents.
- Introduce `BusinessDomain`, `related`, confidence thresholds, hierarchical classifiers, multiple intent models, retries, Planner, ReAct, or dynamic agents.
- Expose LangGraph checkpoint or interrupt identifiers to public clients.
- Add a business-table migration.

## Decisions

### 1. Use route for Graph control and intent for professional behavior

The structured result is one checkpoint-safe value:

~~~text
BusinessUnderstandingResult
├── reasoning: str
├── route: BUSINESS | NON_BUSINESS | CLARIFY
├── intent: BusinessIntent | null
├── entities: BusinessEntities
└── clarification_question: str | null
~~~

Cross-field validation enforces:

- BUSINESS requires an intent and forbids a clarification question.
- NON_BUSINESS requires a null intent and a null clarification question.
- CLARIFY requires one non-blank clarification question and may retain an already-known candidate intent.

This replaces know-engine's `related` gate. A separate `BusinessDomain` is rejected because no V1 consumer changes behavior by industry label; document categories remain future RAG metadata.

Alternatives considered:

- Keep `related` for compatibility: rejected because it duplicates route, permits contradictory output, and cannot represent recoverable missing information.
- Use intent values such as `GENERAL_CHAT` and `CLARIFY` as routes: rejected because execution control and professional answer selection are different concerns.
- Add confidence and threshold routing: deferred until an evaluation demonstrates a useful calibrated threshold.

### 2. Keep one small flat business-intent enum

V1 supports:

~~~text
POLICY_RULE_QA
TRANSPORT_OPERATION_QA
COAL_SALES_QA
PROFESSIONAL_KNOWLEDGE_QA
BUSINESS_DATA_QUERY
OTHER_BUSINESS
~~~

The enum is based on distinct future Prompt or execution behavior, not the knowledge-base directory tree. More granular plan, document, analysis, and exception intents remain evaluation-driven extensions.

Alternative considered:

- Implement every discovered railway business category now: rejected because RAG/SQL consumers do not yet exist and the extra labels would increase ambiguity without changing behavior.

### 3. Invoke structured output from the existing runtime model

`business_understanding` receives the lifespan-initialized model through `ChatRuntimeContext` and derives a structured-output runnable bound to the Pydantic result schema. The node supplies a versioned Prompt asset plus current checkpoint messages and returns only the validated structured result.

Classification JSON and reasoning MUST NOT be streamed to the user. The SSE adapter continues to emit user-visible content only from answer or clarification output.

Invalid schema output fails the node. There is no automatic retry and no fallback to NON_BUSINESS, CLARIFY, or OTHER_BUSINESS because a silent fallback would turn model/protocol failure into an incorrect business decision.

Alternatives considered:

- Create a separate model client inside the node: rejected because it violates the existing lifespan and testability boundary.
- Parse free-form JSON manually: rejected in favor of model structured output plus Pydantic cross-field validation.
- Retry malformed output: deferred because repeated streamed or charged model attempts complicate failure semantics and evaluation.

### 4. Store one latest Business Understanding object in Graph state

`ChatState` continues to extend `MessagesState` and adds one serializable `business_understanding` field. Each successful evaluation overwrites the previous decision; the message history remains the longitudinal context.

The state does not contain model clients, settings, prompt loaders, repositories, pools, or SSE delivery data. User-visible history remains authoritative in business tables, while the checkpoint holds runtime reasoning state.

Alternative considered:

- Flatten every route, intent, and entity into top-level state fields: rejected because it creates a wide state contract and makes atomic validation harder.

### 5. Compile an explicit four-node topology

The stable topology is:

~~~text
START
  ↓
business_understanding
  ├── NON_BUSINESS → llm → END
  ├── BUSINESS → business_boundary → END
  └── CLARIFY → clarify ──interrupt──┐
                         resume      │
                           └─────────┴→ business_understanding
~~~

- `llm` remains the existing general-answer node.
- `business_boundary` returns a deterministic development-stage AI message and MUST NOT invoke the model, RAG, or SQL. This keeps the current completion/persistence contract valid while proving that BUSINESS reached its intended boundary.
- `clarify` calls LangGraph `interrupt` with a typed payload containing the question. After resume it returns both the assistant clarification question and the resumed USER answer as message updates; the static edge then returns to `business_understanding`.

The development-stage business message is intentionally temporary and is replaced when the next business-answer change connects RAG.

Alternatives considered:

- Route BUSINESS directly to END with no assistant message: rejected because the current completion contract requires a durable assistant message before `completed`.
- Send BUSINESS through the general LLM: rejected because it would produce ungrounded business answers.
- Simulate clarification as an ordinary answer followed by a new turn: rejected because it does not exercise checkpoint interrupt/resume and loses the explicit pending state.

### 6. Treat the next owned-conversation message as the resume value

Before a completion run, orchestration inspects the conversation's Graph snapshot using the existing conversation-ID configuration. If the snapshot contains the supported pending Business Understanding interrupt, the producer calls the Graph with `Command(resume=content)`; otherwise it supplies the normal new `HumanMessage` input.

The public completion request shape remains unchanged. Clients cannot submit checkpoint IDs, interrupt IDs, commands, routes, or intents.

The resumed HTTP request still follows the existing durability order:

~~~text
authorize conversation
→ commit USER business message
→ emit metadata
→ Command(resume=user_content)
→ clarify node adds AI clarification + Human response to Graph messages
→ business_understanding re-evaluates
~~~

Only the supported clarify-node interrupt is resumable through this path. Unknown pending tasks or malformed interrupt payloads fail safely.

Alternative considered:

- Add a dedicated public resume endpoint and interrupt token: rejected because one serialized message stream per conversation already provides sufficient identity and ownership.

### 7. Represent an intentional interrupt as completed with finish_reason=interrupt

When Graph streaming surfaces the typed clarification interrupt:

1. The producer extracts the public clarification question.
2. The adapter emits the question as one or more ordered `content_delta` events.
3. The producer persists one ASSISTANT clarification message linked to the initiating USER message.
4. After commit, it emits `completed` with that assistant ID and `finish_reason=interrupt`.
5. The Graph checkpoint remains pending.

An interrupt is not an error, and raw LangGraph interrupt objects are never exposed. A malformed or unsupported interrupt follows the existing error path and does not persist an assistant question.

Using `completed` rather than adding a second terminal SSE event minimizes protocol expansion: the HTTP completion has durably finished, while `finish_reason` tells the client that the conversation runtime awaits input.

Alternative considered:

- Add an `interaction_required` terminal event: rejected for V1 because it would duplicate the existing success-terminal and subscriber cleanup behavior.

### 8. Use Prompt rules and labeled cases as the domain migration boundary

The Prompt includes:

- enterprise freight versus public passenger boundaries;
- policy versus professional-knowledge distinctions;
- process knowledge versus concrete data lookup;
- transportation execution versus coal sales/settlement;
- multi-turn ellipsis and data-version inheritance;
- focused clarification rules;
- valid structured examples for all three routes.

The model returns only a concise decision rationale, not hidden chain-of-thought. The evaluation dataset stores expected route, intent, and only the entities relevant to each case so that sparse optional fields do not dominate the score.

Deterministic unit and integration tests use fake structured models. Live-model comparison remains a manual or separately marked evaluation because it has cost and nondeterminism.

### 9. Serialize one conversation with one coarse Redis completion lock

The complete accepted-completion lifecycle for one conversation is guarded by one Redis distributed lock keyed as `chat:conversation:{conversation_id}:completion`. The design follows the existing `python-redis-lock` infrastructure and the repository's established `auto_renewal=True` pattern instead of holding a database connection or adding a separate task/lease state machine.

For an existing conversation, ownership is checked before lock acquisition so lock state cannot reveal another user's conversation. The non-blocking lock is then acquired before the conversation is mutated or the USER message is persisted. For a new conversation, the server allocates its unique conversation ID before acquiring the same lock. Lock contention fails fast with a conflict and the USER transaction rolls back; Redis unavailability fails closed before Graph execution.

The acquired lock is transferred with the accepted turn to the process-owned completion task. It remains held across metadata publication, checkpoint inspection, normal input or `Command(resume=...)`, Graph streaming, ASSISTANT persistence, and the completed/error terminal path. Browser disconnect only detaches the subscriber and does not release the lock. The producer registry releases the lock in a task-level `finally` block on success, failure, cancellation, or application shutdown. Auto renewal keeps a long model run from expiring the lock, while the Redis expiry remains crash recovery if the owning process disappears.

This is deliberately coarse grained: there are no separate locks for snapshot inspection, resume, Graph nodes, or message persistence, and no local-only `asyncio.Lock`. Different conversation IDs remain independent.

Alternatives considered:

- PostgreSQL advisory lock: rejected because a long model run would reserve a database connection or transaction for the entire generation.
- Process-local lock: rejected because multiple API workers could still race the same checkpoint.
- Redis task lease/fencing state machine: deferred because the current requirement is only one active completion per conversation, and the existing lock library already provides owner-token release, expiry, and renewal.

## Risks / Trade-offs

- [Prompt may overuse CLARIFY for optional fields] → Include positive “answer without optional ID/time/version” cases and assert focused clarification only for execution-critical information.
- [The same model handles classification and general answering] → Keep dependency injection ready for a later dedicated classifier, but avoid a second model configuration before evaluation shows a need.
- [The wide nullable entity schema can become sparse] → Limit fields to known railway/coal consumers and evaluate key-entity recall separately from exact full-object equality.
- [Persisted clarification exists in the business table before it enters Graph messages] → On resume, the clarify node atomically adds the same question plus the user response to checkpoint message state; business history and checkpoint retain their existing separate responsibilities.
- [A process crash after assistant clarification commit but before the interrupt terminal event leaves the client uncertain] → Persisted message history remains authoritative; no automatic retry or replay is introduced in this change.
- [Old checkpoints follow the previous single-node topology] → This project has no active users; deploy the topology as a development migration and discard incompatible development checkpoints if necessary.
- [The deterministic BUSINESS boundary answer is not a real business response] → Use explicit wording, prohibit ungrounded LLM calls, and replace the boundary node in the next RAG change.
- [Public clients may assume finish_reason is always stop] → Update backend and frontend enums/tests together; treat `interrupt` as a successful terminal that allows the next user send.
- [A second request arrives while one conversation is generating] → Fail fast before persisting the second USER message; the client can retry after the active completion reaches its terminal path.
- [Redis is unavailable during completion admission] → Fail closed and do not persist the USER message or start Graph execution, because running without the lock would reintroduce checkpoint races.

## Migration Plan

1. Add schema, Prompt, state, nodes, router, and graph tests while preserving the existing `llm` node.
2. Add interrupt adaptation, persistence, resume detection, and API/SSE integration tests.
3. Update public/backend/frontend `finish_reason` typing to accept `interrupt`.
4. Run existing Chat runtime, persistence, SSE disconnect, and API suites plus the new route and resume suites.
5. Deploy only after incompatible development checkpoints are cleared or confirmed absent; no business-table migration is required.
6. Roll back by restoring the prior graph builder and terminal enum. Any checkpoint suspended inside the new clarification node must be discarded before rollback because the old topology cannot resume it.

## Open Questions

No blocking design questions remain for this change. The exact deterministic BUSINESS boundary wording is an implementation constant and does not affect the routing contract.
