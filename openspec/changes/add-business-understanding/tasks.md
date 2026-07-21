## 1. Structured Contract and Prompt

- [ ] 1.1 Add failing unit tests for BusinessRoute, BusinessIntent, entity fields, cross-field result invariants, unsupported labels, and the absence of related/BusinessDomain/confidence.
- [ ] 1.2 Implement the Pydantic enums and structured BusinessUnderstandingResult/BusinessEntities models required by the tests.
- [ ] 1.3 Add the versioned railway-and-coal Business Understanding Prompt with route rules, six business intents, entity definitions, disambiguation rules, and valid BUSINESS/NON_BUSINESS/CLARIFY examples.
- [ ] 1.4 Add the labeled offline evaluation dataset covering public-passenger negatives, policy versus professional knowledge, process versus data lookup, transportation versus coal sales, multi-turn ellipsis, entities, and focused clarification.

## 2. Chat Graph Routing

- [ ] 2.1 Add failing async node tests that inject a fake structured model and assert valid state updates, invalid-output failure, no automatic retry, and no infrastructure construction.
- [ ] 2.2 Extend ChatState with one checkpoint-serializable latest Business Understanding object and implement the business_understanding node using the runtime-injected model.
- [ ] 2.3 Add failing topology tests for NON_BUSINESS, BUSINESS, initial CLARIFY suspension, resumed clarification message updates, and re-evaluation after resume.
- [ ] 2.4 Implement the conditional router and compile the business_understanding, existing llm, deterministic business_boundary, and interrupting clarify nodes according to the specified topology.
- [ ] 2.5 Verify that classification JSON/reasoning is not emitted as public content and that the BUSINESS boundary invokes neither the model nor RAG/SQL.

## 3. Clarification Persistence and Resume

- [ ] 3.1 Add failing completion-producer tests for typed interrupt extraction, clarification content delivery, ASSISTANT persistence before terminal delivery, malformed-interrupt failure, and browser-disconnect continuation.
- [ ] 3.2 Extend backend SSE models so completed accepts finish_reason=interrupt while preserving finish_reason=stop for ordinary answers.
- [ ] 3.3 Implement producer adaptation that turns a supported Graph interrupt into content_delta output, persists the clarification question, and emits completed only after commit without exposing LangGraph internals.
- [ ] 3.4 Add failing orchestration/API tests for pending-checkpoint detection, USER commit before resume, owner concealment, normal-turn fallback, and rejection of client-controlled resume internals.
- [ ] 3.5 Implement snapshot inspection and Command(resume=user_content) for the next owned-conversation message while leaving the public completion request shape unchanged.
- [ ] 3.6 Update frontend/client finish-reason typing and stream completion handling so interrupt is a successful terminal and the user can submit the next clarification response.

## 4. End-to-End Verification

- [ ] 4.1 Add PostgreSQL-checkpointer integration tests that exercise one complete CLARIFY request, persisted clarification question, next-message resume, Business Understanding re-evaluation, and final branch completion on the same conversation thread.
- [ ] 4.2 Add integration tests proving NON_BUSINESS still streams and persists the general-model answer and BUSINESS persists only the deterministic boundary answer.
- [ ] 4.3 Run the existing Chat Graph, conversation API, SSE ordering, disconnect, persistence, and lifecycle suites and fix only regressions introduced by this change.
- [ ] 4.4 Run the deterministic Business Understanding evaluation, report route/intent/entity/clarification/schema results separately, and record any unresolved bad cases without inventing live-model accuracy.
- [ ] 4.5 Update the Chat runtime and Prompt-optimization documentation with the implemented topology, final public finish reasons, verification commands, and deferred RAG/SQL scope.
