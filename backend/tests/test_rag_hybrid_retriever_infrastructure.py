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
    options = DocumentRetrievalOptions(
        result_limit=12,
        candidate_limit=60,
    )
    factory = DocumentHybridRetrieverFactory(
        client=client,
        store=store,
        index_name="rag-documents",
        options=options,
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

        def similarity_search_with_score(self, query, **kwargs):
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
    assert retriever.retrieval_stages == {
        "BM25": {
            "resultCount": 1,
            "scoreType": "ELASTICSEARCH_BM25",
            "ranking": [
                {
                    "rank": 1,
                    "chunkId": "full-text",
                    "docId": "doc-full-text",
                    "score": 8.5,
                    "textPreview": "全文结果",
                }
            ],
        },
        "VECTOR": {
            "resultCount": 2,
            "scoreType": "ELASTICSEARCH_KNN",
            "minScore": 0.5,
            "fetchedCount": 3,
            "filteredOutCount": 1,
            "ranking": [
                {
                    "rank": 1,
                    "chunkId": "full-text",
                    "docId": "doc-full-text",
                    "score": 0.91,
                    "textPreview": "full-text",
                },
                {
                    "rank": 2,
                    "chunkId": "vector",
                    "docId": "doc-vector",
                    "score": 0.82,
                    "textPreview": "vector",
                }
            ],
        },
        "RRF": {
            "resultCount": 2,
            "rankConstant": 60,
            "ranking": [
                {
                    "rank": 1,
                    "chunkId": "full-text",
                    "docId": "doc-full-text",
                    "rrfScore": 2 / 61,
                    "channels": {
                        "BM25": {
                            "rank": 1,
                            "score": 8.5,
                            "rrfContribution": 1 / 61,
                        },
                        "VECTOR": {
                            "rank": 1,
                            "score": 0.91,
                            "rrfContribution": 1 / 61,
                        }
                    },
                    "textPreview": "全文结果",
                },
                {
                    "rank": 2,
                    "chunkId": "vector",
                    "docId": "doc-vector",
                    "rrfScore": 1 / 62,
                    "channels": {
                        "VECTOR": {
                            "rank": 2,
                            "score": 0.82,
                            "rrfContribution": 1 / 62,
                        }
                    },
                    "textPreview": "vector",
                },
            ],
        },
    }


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

    retriever = ElasticsearchHybridRetriever(
        client=FakeClient(),
        store=FakeStore(),
        index_name="rag-documents",
        scope=DocumentRetrievalScope(accessibleBy=["team-a"]),
        options=DocumentRetrievalOptions(),
    )

    assert await retriever.ainvoke("合同") == []
    assert retriever.retrieval_stages == {
        "BM25": {
            "resultCount": 0,
            "scoreType": "ELASTICSEARCH_BM25",
            "ranking": [],
        },
        "VECTOR": {
            "resultCount": 0,
            "scoreType": "ELASTICSEARCH_KNN",
            "minScore": 0.5,
            "fetchedCount": 0,
            "filteredOutCount": 0,
            "ranking": [],
        },
        "RRF": {
            "resultCount": 0,
            "rankConstant": 60,
            "ranking": [],
        },
    }


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
    )

    with pytest.raises(RuntimeError, match="full text unavailable"):
        await retriever.ainvoke("合同")
