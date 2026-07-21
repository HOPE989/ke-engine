## 1. Langfuse dependency and resources

- [x] 1.1 Add Langfuse runtime and LangGraph CLI development dependencies with a refreshed uv lockfile
- [x] 1.2 Add standard Langfuse connection, environment and release Settings fields without an enable switch
- [x] 1.3 Implement one concrete optional Langfuse client/handler resource pair
- [x] 1.4 Implement fail-open completion observation entry, update, cleanup and asynchronous shutdown
- [x] 1.5 Add offline tests for missing configuration and failures at every Langfuse lifecycle boundary

## 2. Production Chat tracing

- [x] 2.1 Create and close optional Langfuse resources in Chat API lifespan after managed producers
- [x] 2.2 Pass the optional resource through Chat dependencies and Router to each CompletionProducer
- [x] 2.3 Wrap each accepted completion in one root observation with raw input, session, user and model attributes
- [x] 2.4 Add the callback only to the Chat Graph invocation and record input mode plus terminal output
- [x] 2.5 Prove tracing failures preserve existing success, error, interrupt, disconnect and shutdown semantics

## 3. Thin Studio adapter

- [x] 3.1 Extract model-explicit cores from the two model-dependent nodes without changing their behavior
- [x] 3.2 Add optional bound-model mode to the existing graph builder while preserving the production runtime context mode
- [x] 3.3 Allow Chat model construction to receive optional callbacks
- [x] 3.4 Add the Studio graph factory and langgraph.json without importing FastAPI business resources
- [x] 3.5 Add tests proving bound execution, identical topology and absence of production database, Redis, saver, Registry, SSE and title model setup

## 4. Business-understanding Dataset and scoring

- [x] 4.1 Map all 18 repository cases to stable Langfuse Dataset item IDs and payloads
- [x] 4.2 Reconstruct EvaluationCase from Langfuse inputs and reuse the existing five-dimension scorer
- [x] 4.3 Convert the five numerator/denominator results to numeric Langfuse Evaluations with explanatory details
- [x] 4.4 Execute the real business-understanding node from each Dataset item using complete LangChain message history
- [x] 4.5 Add offline mapping, scoring and real-node task tests with fake model and SDK objects

## 5. Live Experiment command

- [ ] 5.1 Create or reuse the fixed Dataset and idempotently upsert the 18 current cases
- [ ] 5.2 Run a serial Dataset Experiment with real model callback tracing and live_model metadata
- [ ] 5.3 Print formatted results and Dataset Run URL and return non-zero for configuration, authentication or remote failures
- [ ] 5.4 Document Langfuse configuration, Chat tracing, Studio and Experiment commands
- [ ] 5.5 Add offline orchestration tests proving serial execution, fail-fast behavior and guaranteed client shutdown

## 6. Verification and evidence

- [ ] 6.1 Run focused Langfuse, Graph, Chat and evaluation tests
- [ ] 6.2 Run the complete backend non-integration suite without network access
- [ ] 6.3 Verify the installed LangGraph CLI exposes the local dev command
- [ ] 6.4 Run strict OpenSpec validation and git diff checks
- [ ] 6.5 Review the complete change for masked business exceptions, duplicate topology, accidental infrastructure tracing and silent Experiment success
- [ ] 6.6 Record exact verification evidence and keep live-model execution explicitly manual without credentials
