import threading
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever


def _settings():
    return SimpleNamespace(
        elasticsearch_url="http://elasticsearch.example:9200",
        elasticsearch_index="rag-documents",
        embedding_dimensions=1536,
    )


def _document(chunk_id: str, text: str | None = None) -> Document:
    return Document(
        page_content=text or chunk_id,
        metadata={
            "chunkId": chunk_id,
            "docId": f"doc-{chunk_id}",
        },
    )


class _FakeReranker:
    def __init__(self, scores=None, *, error=None):
        self.scores = scores
        self.error = error
        self.calls = []

    async def rerank(self, query, documents):
        from app.infrastructure.rerank import (
            RerankResult,
            RerankScore,
        )

        self.calls.append((query, list(documents)))
        if self.error is not None:
            raise self.error
        scores = (
            list(self.scores)
            if self.scores is not None
            else [1.0] * len(documents)
        )
        return RerankResult(
            request_id="fake-rerank-request",
            scores=tuple(
                RerankScore(index=index, relevance_score=score)
                for index, score in enumerate(scores)
            ),
        )


def test_retrieval_store_reuses_client_without_native_hybrid(monkeypatch):
    from app.infrastructure import elasticsearch as infrastructure

    captured = {}

    class FakeElasticsearchStore:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        infrastructure,
        "ElasticsearchStore",
        FakeElasticsearchStore,
    )
    client = object()
    embedding_model = object()

    store = infrastructure.create_document_retrieval_store(
        settings=_settings(),
        embedding_model=embedding_model,
        client=client,
    )

    assert isinstance(store, FakeElasticsearchStore)
    assert captured["client"] is client
    assert "es_url" not in captured
    assert captured["index_name"] == "rag-documents"
    assert captured["embedding"] is embedding_model
    assert captured["query_field"] == "text"
    assert captured["vector_query_field"] == "vector"
    assert captured["num_dimensions"] == 1536
    assert captured["strategy"].hybrid is False


def test_application_rrf_deduplicates_orders_and_limits_by_chunk_id():
    from app.infrastructure.elasticsearch import reciprocal_rank_fusion

    full_text = [
        _document("a"),
        _document("b"),
        _document("c"),
    ]
    vector = [
        _document("b"),
        _document("d"),
        _document("a"),
    ]

    fused = reciprocal_rank_fusion(
        [full_text, vector],
        rank_constant=60,
        result_limit=3,
    )

    assert [document.metadata["chunkId"] for document in fused] == [
        "b",
        "a",
        "d",
    ]


def test_application_rrf_breaks_score_ties_by_chunk_id():
    from app.infrastructure.elasticsearch import reciprocal_rank_fusion

    fused = reciprocal_rank_fusion(
        [[_document("z")], [_document("a")]],
        rank_constant=60,
        result_limit=10,
    )
    reversed_fused = reciprocal_rank_fusion(
        [[_document("a")], [_document("z")]],
        rank_constant=60,
        result_limit=10,
    )

    assert [document.metadata["chunkId"] for document in fused] == [
        "a",
        "z",
    ]
    assert [
        document.metadata["chunkId"] for document in reversed_fused
    ] == ["a", "z"]


def test_application_rrf_rejects_document_without_chunk_id():
    from app.infrastructure.elasticsearch import reciprocal_rank_fusion

    with pytest.raises(ValueError, match="chunkId"):
        reciprocal_rank_fusion(
            [[Document(page_content="missing identity")]],
            rank_constant=60,
            result_limit=10,
        )


def test_document_retrieval_filters_require_scope_and_include_doc_ids():
    from app.domains.rag.graph.retrieval import DocumentRetrievalScope
    from app.infrastructure.elasticsearch import (
        build_document_retrieval_filters,
    )

    filters = build_document_retrieval_filters(
        DocumentRetrievalScope(
            accessibleBy=["team-b", "team-a"],
            docIds=["42", "7"],
        )
    )

    assert filters == [
        {
            "terms": {
                "metadata.accessibleBy": ["team-a", "team-b"],
            }
        },
        {"terms": {"metadata.docId": ["42", "7"]}},
    ]


def test_document_retrieval_filters_omit_unset_doc_ids():
    from app.domains.rag.graph.retrieval import DocumentRetrievalScope
    from app.infrastructure.elasticsearch import (
        build_document_retrieval_filters,
    )

    filters = build_document_retrieval_filters(
        DocumentRetrievalScope(accessibleBy=["team-a"])
    )

    assert filters == [
        {"terms": {"metadata.accessibleBy": ["team-a"]}}
    ]


def test_request_scoped_factory_creates_custom_base_retrievers():
    from app.domains.rag.graph.retrieval import (
        DocumentRetrievalOptions,
        DocumentRetrievalScope,
    )
    from app.infrastructure.elasticsearch import (
        DocumentHybridRetrieverFactory,
        ElasticsearchHybridRetriever,
    )

    client = object()
    store = object()
    parent_chunk_cache = object()
    reranker = _FakeReranker()
    options = DocumentRetrievalOptions(
        result_limit=12,
        candidate_limit=60,
    )
    factory = DocumentHybridRetrieverFactory(
        client=client,
        store=store,
        index_name="rag-documents",
        options=options,
        reranker=reranker,
        parent_chunk_cache=parent_chunk_cache,
    )

    first_scope = DocumentRetrievalScope(
        accessibleBy=["team-a"]
    )
    second_scope = DocumentRetrievalScope(
        accessibleBy=["team-b"]
    )
    first = factory.create(first_scope)
    second = factory.create(second_scope)

    assert isinstance(first, BaseRetriever)
    assert isinstance(first, ElasticsearchHybridRetriever)
    assert first is not second
    assert first.client is client
    assert first.store is store
    assert first.index_name == "rag-documents"
    assert first.scope == first_scope
    assert first.options is options
    assert first.reranker is reranker
    assert first.parent_chunk_cache is parent_chunk_cache
    assert second.scope == second_scope


def test_sync_hybrid_retriever_applies_identical_filters():
    from app.domains.rag.graph.retrieval import (
        DocumentRetrievalOptions,
        DocumentRetrievalScope,
    )
    from app.infrastructure.elasticsearch import (
        ElasticsearchHybridRetriever,
    )

    class FakeClient:
        def __init__(self):
            self.calls = []

        def search(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "hits": {
                    "hits": [
                        {
                            "_score": 8.5,
                            "_source": {
                                "text": "全文结果",
                                "metadata": {
                                    "chunkId": "full-text",
                                    "docId": "doc-full-text",
                                },
                            }
                        }
                    ]
                }
            }

    class FakeStore:
        def __init__(self):
            self.calls = []

        async def asimilarity_search_with_score(self, query, **kwargs):
            self.calls.append((query, kwargs))
            return [
                (_document("full-text"), 0.91),
                (_document("vector"), 0.82),
                (_document("below-threshold"), 0.49),
            ]

    client = FakeClient()
    store = FakeStore()
    retriever = ElasticsearchHybridRetriever(
        client=client,
        store=store,
        index_name="rag-documents",
        scope=DocumentRetrievalScope(
            accessibleBy=["team-a"],
            docIds=["doc-full-text"],
        ),
        options=DocumentRetrievalOptions(
            result_limit=3,
            candidate_limit=5,
        ),
        reranker=_FakeReranker(),
    )

    documents = retriever.invoke("合同付款周期")

    expected_filters = [
        {"terms": {"metadata.accessibleBy": ["team-a"]}},
        {"terms": {"metadata.docId": ["doc-full-text"]}},
    ]
    assert [
        document.metadata["chunkId"] for document in documents
    ] == ["full-text", "vector"]
    assert client.calls == [
        {
            "index": "rag-documents",
            "size": 5,
            "query": {
                "bool": {
                    "must": [
                        {
                            "match": {
                                "text": {
                                    "query": "合同付款周期",
                                }
                            }
                        }
                    ],
                    "filter": expected_filters,
                }
            },
        }
    ]
    assert store.calls == [
        (
            "合同付款周期",
            {
                "k": 5,
                "filter": expected_filters,
            },
        )
    ]
    stages = retriever.retrieval_stages
    assert list(stages) == [
        "RECALL",
        "PARENT_EXPANSION",
        "RRF",
        "RERANK",
    ]
    assert [
        item["chunkId"]
        for item in stages["PARENT_EXPANSION"]["VECTOR"]
    ] == ["full-text", "vector"]
    assert [
        item["chunkId"] for item in stages["RRF"]
    ] == ["full-text", "vector"]
    assert [
        item["score"] for item in stages["RERANK"]["candidates"]
    ] == [1.0, 1.0]


@pytest.mark.asyncio
async def test_async_hybrid_retriever_starts_bm25_and_knn_concurrently():
    from app.domains.rag.graph.retrieval import (
        DocumentRetrievalOptions,
        DocumentRetrievalScope,
    )
    from app.infrastructure.elasticsearch import (
        ElasticsearchHybridRetriever,
    )

    full_text_started = threading.Event()
    vector_started = threading.Event()

    class FakeClient:
        def search(self, **kwargs):
            del kwargs
            full_text_started.set()
            assert vector_started.wait(timeout=1)
            return {"hits": {"hits": []}}

    class FakeStore:
        async def asimilarity_search_with_score(self, query, **kwargs):
            del query, kwargs
            vector_started.set()
            assert full_text_started.wait(timeout=1)
            return []

    reranker = _FakeReranker()
    retriever = ElasticsearchHybridRetriever(
        client=FakeClient(),
        store=FakeStore(),
        index_name="rag-documents",
        scope=DocumentRetrievalScope(accessibleBy=["team-a"]),
        options=DocumentRetrievalOptions(),
        reranker=reranker,
    )

    assert await retriever.ainvoke("合同") == []
    assert retriever.retrieval_stages == {
        "RECALL": {"BM25": [], "VECTOR": []},
        "PARENT_EXPANSION": {"BM25": [], "VECTOR": []},
        "RRF": [],
        "RERANK": {
            "model": "qwen3-rerank",
            "durationMs": 0,
            "threshold": 0.6,
            "resultLimit": 5,
            "skipped": True,
            "candidates": [],
        },
    }
    assert reranker.calls == []


@pytest.mark.asyncio
async def test_async_hybrid_retriever_replaces_and_deduplicates_parent_chunks():
    from app.domains.rag.graph.retrieval import (
        DocumentRetrievalOptions,
        DocumentRetrievalScope,
    )
    from app.infrastructure.elasticsearch import (
        ElasticsearchHybridRetriever,
    )

    def child(chunk_id: str) -> Document:
        return Document(
            page_content=f"子分段 {chunk_id}",
            metadata={
                "chunkId": chunk_id,
                "docId": "1001",
                "parentChunkId": "parent-1",
                "fileName": "合同.md",
            },
        )

    normal = Document(
        page_content="独立分段",
        metadata={
            "chunkId": "normal",
            "docId": "1001",
            "parentChunkId": None,
        },
    )

    class FakeClient:
        def search(self, **kwargs):
            del kwargs
            return {
                "hits": {
                    "hits": [
                        {
                            "_score": 9.0,
                            "_source": {
                                "text": child("child-a").page_content,
                                "metadata": child("child-a").metadata,
                            },
                        },
                        {
                            "_score": 8.0,
                            "_source": {
                                "text": child("child-b").page_content,
                                "metadata": child("child-b").metadata,
                            },
                        },
                        {
                            "_score": 7.0,
                            "_source": {
                                "text": normal.page_content,
                                "metadata": normal.metadata,
                            },
                        },
                    ]
                }
            }

    class FakeStore:
        async def asimilarity_search_with_score(self, query, **kwargs):
            del query, kwargs
            return [(child("child-c"), 0.9)]

    class FakeParentChunkCache:
        def __init__(self):
            self.calls = []

        async def load(self, references):
            self.calls.append(references)
            return {("1001", "parent-1"): "父分段完整正文"}

    parent_chunk_cache = FakeParentChunkCache()
    reranker = _FakeReranker([0.9, 0.6])

    retriever = ElasticsearchHybridRetriever(
        client=FakeClient(),
        store=FakeStore(),
        index_name="rag-documents",
        scope=DocumentRetrievalScope(accessibleBy=["team-a"]),
        options=DocumentRetrievalOptions(
            result_limit=2,
            candidate_limit=4,
        ),
        reranker=reranker,
        parent_chunk_cache=parent_chunk_cache,
    )

    documents = await retriever.ainvoke("合同")

    assert parent_chunk_cache.calls == [
        (("1001", "parent-1"),),
        (("1001", "parent-1"),),
    ]
    assert [document.page_content for document in documents] == [
        "父分段完整正文",
        "独立分段",
    ]
    assert documents[0].metadata == {
        **child("child-a").metadata,
        "chunkId": "parent-1",
        "matchedChunkId": "child-a",
        "rerankScore": 0.9,
    }
    assert [
        item["chunkId"]
        for item in retriever.retrieval_stages["RECALL"]["BM25"]
    ] == ["child-a", "child-b", "normal"]
    assert retriever.retrieval_stages["PARENT_EXPANSION"] == {
        "BM25": [
            {
                "rank": 1,
                "sourceRank": 1,
                "chunkId": "parent-1",
                "score": 9.0,
                "textPreview": "父分段完整正文",
                "fromChunkId": "child-a",
            },
            {
                "rank": 2,
                "sourceRank": 3,
                "chunkId": "normal",
                "score": 7.0,
                "textPreview": "独立分段",
            },
        ],
        "VECTOR": [
            {
                "rank": 1,
                "sourceRank": 1,
                "chunkId": "parent-1",
                "score": 0.9,
                "textPreview": "父分段完整正文",
                "fromChunkId": "child-c",
            }
        ],
    }
    assert retriever.retrieval_stages["RRF"] == [
        {
            "rank": 1,
            "chunkId": "parent-1",
            "rrfScore": 2 / 61,
            "channels": {
                "BM25": {
                    "rank": 1,
                    "score": 9.0,
                    "rrfContribution": 1 / 61,
                },
                "VECTOR": {
                    "rank": 1,
                    "score": 0.9,
                    "rrfContribution": 1 / 61,
                },
            },
            "textPreview": "父分段完整正文",
        },
        {
            "rank": 2,
            "chunkId": "normal",
            "rrfScore": 1 / 62,
            "channels": {
                "BM25": {
                    "rank": 2,
                    "score": 7.0,
                    "rrfContribution": 1 / 62,
                }
            },
            "textPreview": "独立分段",
        },
    ]
    assert reranker.calls == [
        ("合同", ["父分段完整正文", "独立分段"])
    ]
    assert retriever.retrieval_stages["RERANK"][
        "candidates"
    ] == [
        {
            "rrfRank": 1,
            "rerankRank": 1,
            "chunkId": "parent-1",
            "score": 0.9,
            "passed": True,
            "textPreview": "父分段完整正文",
        },
        {
            "rrfRank": 2,
            "rerankRank": 2,
            "chunkId": "normal",
            "score": 0.6,
            "passed": True,
            "textPreview": "独立分段",
        },
    ]


@pytest.mark.asyncio
async def test_async_hybrid_retriever_reranks_ten_filters_and_returns_top_five():
    from app.domains.rag.graph.retrieval import (
        DocumentRetrievalOptions,
        DocumentRetrievalScope,
    )
    from app.infrastructure.elasticsearch import (
        ElasticsearchHybridRetriever,
    )

    documents = [_document(f"chunk-{index}") for index in range(10)]

    class FakeClient:
        def search(self, **kwargs):
            assert kwargs["size"] == 10
            return {
                "hits": {
                    "hits": [
                        {
                            "_score": float(10 - index),
                            "_source": {
                                "text": document.page_content,
                                "metadata": document.metadata,
                            },
                        }
                        for index, document in enumerate(documents)
                    ]
                }
            }

    class FakeStore:
        async def asimilarity_search_with_score(self, query, **kwargs):
            del query
            assert kwargs["k"] == 10
            return [
                (document, 0.9)
                for document in reversed(documents)
            ]

    scores = [0.61, 0.99, 0.6, 0.8, 0.7, 0.95, 0.59, 0.4, 0.3, 0.2]
    reranker = _FakeReranker(scores)
    retriever = ElasticsearchHybridRetriever(
        client=FakeClient(),
        store=FakeStore(),
        index_name="rag-documents",
        scope=DocumentRetrievalScope(accessibleBy=["team-a"]),
        options=DocumentRetrievalOptions(),
        reranker=reranker,
    )

    retained = await retriever.ainvoke("合同")

    assert len(retriever.retrieval_stages["RRF"]) == 10
    assert len(reranker.calls) == 1
    assert len(reranker.calls[0][1]) == 10
    assert [item.metadata["rerankScore"] for item in retained] == [
        0.99,
        0.95,
        0.8,
        0.7,
        0.61,
    ]
    assert retained[0].page_content == reranker.calls[0][1][1]
    assert all(
        item.metadata["rerankScore"] >= 0.6
        for item in retained
    )


@pytest.mark.asyncio
async def test_async_hybrid_retriever_returns_empty_when_all_scores_fail():
    from app.domains.rag.graph.retrieval import (
        DocumentRetrievalOptions,
        DocumentRetrievalScope,
    )
    from app.infrastructure.elasticsearch import (
        ElasticsearchHybridRetriever,
    )

    document = _document("chunk-1")

    class FakeClient:
        def search(self, **kwargs):
            del kwargs
            return {
                "hits": {
                    "hits": [
                        {
                            "_score": 1.0,
                            "_source": {
                                "text": document.page_content,
                                "metadata": document.metadata,
                            },
                        }
                    ]
                }
            }

    class FakeStore:
        async def asimilarity_search_with_score(self, query, **kwargs):
            del query, kwargs
            return []

    retriever = ElasticsearchHybridRetriever(
        client=FakeClient(),
        store=FakeStore(),
        index_name="rag-documents",
        scope=DocumentRetrievalScope(accessibleBy=["team-a"]),
        options=DocumentRetrievalOptions(),
        reranker=_FakeReranker([0.59]),
    )

    assert await retriever.ainvoke("合同") == []
    assert retriever.retrieval_stages["RERANK"]["candidates"] == [
        {
            "rrfRank": 1,
            "rerankRank": 1,
            "chunkId": "chunk-1",
            "score": 0.59,
            "passed": False,
            "textPreview": "chunk-1",
        }
    ]


@pytest.mark.asyncio
async def test_async_hybrid_retriever_propagates_rerank_failure():
    from app.domains.rag.graph.retrieval import (
        DocumentRetrievalOptions,
        DocumentRetrievalScope,
    )
    from app.infrastructure.elasticsearch import (
        ElasticsearchHybridRetriever,
    )

    document = _document("chunk-1")

    class FakeClient:
        def search(self, **kwargs):
            del kwargs
            return {
                "hits": {
                    "hits": [
                        {
                            "_score": 1.0,
                            "_source": {
                                "text": document.page_content,
                                "metadata": document.metadata,
                            },
                        }
                    ]
                }
            }

    class FakeStore:
        async def asimilarity_search_with_score(self, query, **kwargs):
            del query, kwargs
            return []

    retriever = ElasticsearchHybridRetriever(
        client=FakeClient(),
        store=FakeStore(),
        index_name="rag-documents",
        scope=DocumentRetrievalScope(accessibleBy=["team-a"]),
        options=DocumentRetrievalOptions(),
        reranker=_FakeReranker(
            error=RuntimeError("provider unavailable")
        ),
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await retriever.ainvoke("合同")


@pytest.mark.asyncio
async def test_segment_repository_batches_parent_reads_by_document_and_chunk():
    from app.domains.document.repositories.segment_repository import (
        SegmentRepository,
    )

    class FakeResult:
        def all(self):
            return [
                (1001, "parent-a", "父分段 A"),
                (1002, "parent-b", "父分段 B"),
            ]

    class FakeSession:
        def __init__(self):
            self.statement = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb

        async def execute(self, statement):
            self.statement = statement
            return FakeResult()

    session = FakeSession()
    repository = SegmentRepository(lambda: session)

    texts = await repository.get_parent_texts(
        [
            ("1001", "parent-a"),
            ("1001", "parent-a"),
            ("1002", "parent-b"),
        ]
    )

    assert texts == {
        ("1001", "parent-a"): "父分段 A",
        ("1002", "parent-b"): "父分段 B",
    }
    assert session.statement is not None
    compiled_params = session.statement.compile().params
    assert sorted(compiled_params["param_1"]) == [
        (1001, "parent-a"),
        (1002, "parent-b"),
    ]


@pytest.mark.asyncio
async def test_async_hybrid_retriever_propagates_subsearch_failure():
    from app.domains.rag.graph.retrieval import (
        DocumentRetrievalOptions,
        DocumentRetrievalScope,
    )
    from app.infrastructure.elasticsearch import (
        ElasticsearchHybridRetriever,
    )

    class FakeClient:
        def search(self, **kwargs):
            del kwargs
            raise RuntimeError("full text unavailable")

    class FakeStore:
        async def asimilarity_search_with_score(self, query, **kwargs):
            del query, kwargs
            return []

    retriever = ElasticsearchHybridRetriever(
        client=FakeClient(),
        store=FakeStore(),
        index_name="rag-documents",
        scope=DocumentRetrievalScope(accessibleBy=["team-a"]),
        options=DocumentRetrievalOptions(),
        reranker=_FakeReranker(),
    )

    with pytest.raises(RuntimeError, match="full text unavailable"):
        await retriever.ainvoke("合同")
