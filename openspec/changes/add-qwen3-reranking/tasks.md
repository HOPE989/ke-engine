## 1. Retrieval contract

- [ ] 1.1 Keep `DocumentRetrievalOptions` unchanged, reuse `candidate_limit=10` for RRF and `result_limit=5` for final output, and define constants only for model, Q&A instruction, and minimum score `0.6`.
- [ ] 1.2 Extend `DocumentCandidate` with provider-backed `rerankScore` and update Graph projection for retained parent Documents.
- [ ] 1.3 Add contract tests for candidate serialization and the inclusive `score >= 0.6` boundary.

## 2. Bailian Qwen3 Rerank client

- [ ] 2.1 Add a focused asynchronous Rerank client and minimal result types with an injectable HTTP transport.
- [ ] 2.2 Implement safe derivation of `/compatible-api/v1/reranks` from the existing `OPENAI_BASE_URL` Workspace origin and reuse `OPENAI_API_KEY` for Bearer authorization.
- [ ] 2.3 Implement one asynchronous `qwen3-rerank` request with the fixed Q&A instruction, dynamic `top_n`, existing retrieval timeout, and no retry or endpoint probing.
- [ ] 2.4 Parse the documented request ID plus result index and relevance score fields; let HTTP or parsing errors propagate without response repair or partial-result fallback.
- [ ] 2.5 Add offline HTTP mock tests for the request payload, normal response, provider error, and malformed required fields.

## 3. Hybrid Retriever integration

- [ ] 3.1 Inject the Rerank client through `DocumentHybridRetrieverFactory` into each request-scoped `ElasticsearchHybridRetriever` without changing authorization filters or parent loading.
- [ ] 3.2 Let RRF return up to the existing `candidate_limit=10` while preserving per-channel parent expansion, highest-ranked parent deduplication, and stable parent `chunkId`.
- [ ] 3.3 Invoke Qwen3 once with all RRF parents, map scores by input index, deterministically sort by score/RRF rank/chunk ID, retain `score >= 0.6`, and return at most five Documents.
- [ ] 3.4 Skip Bailian when RRF is empty, return an empty list when every valid score is filtered, and attach `rerankScore` only to successfully scored parent Documents.
- [ ] 3.5 Let provider or parsing failures surface to the Graph node as the existing `FAILED` outcome, without retry, probing, partial results, or unreranked fallback.

## 4. Diagnostics and runtime assembly

- [ ] 4.1 Extend Retriever stages with a compact `RERANK` stage containing model, request ID, duration, threshold, ranks, scores, and pass/fail decisions.
- [ ] 4.2 Ensure total retrieval duration includes Rerank while diagnostics and logs exclude credentials, Base URLs, complete query/document text, raw responses, and raw exception messages.
- [ ] 4.3 Assemble one process-lifetime async HTTP transport and the Rerank client in `rag_studio.py` using existing OpenAI settings, without adding environment variables or changing Chat/Embedding clients.
- [ ] 4.4 Update RAG Studio and Graph assembly tests to inject fake Rerank resources and verify existing settings are reused unchanged.

## 5. End-to-end behavior and verification

- [ ] 5.1 Extend Hybrid Retriever offline tests for `10 + 10 → parent RRF 10 → score >= 0.6 → Top5`, rerank promotion, parent-only scoring, and matched child metadata.
- [ ] 5.2 Extend `document_hybrid` node tests for retained-result `SUCCESS`, no-recall `EMPTY`, all-filtered `EMPTY`, and provider `FAILED`.
- [ ] 5.3 Keep explicit Elasticsearch integration tests independent of Bailian by injecting a deterministic fake Reranker while continuing to verify real BM25/KNN, parent expansion, RRF, filters, and Basic License compatibility.
- [ ] 5.4 Run targeted Rerank/Hybrid/Graph tests and the default backend checks; resolve regressions without adding configuration or fallback branches.
