from types import SimpleNamespace


def _settings():
    return SimpleNamespace(
        elasticsearch_url="http://elasticsearch.example:9200",
        elasticsearch_index="rag-documents",
        embedding_dimensions=1536,
    )


def test_hybrid_store_reuses_client_and_configures_native_rrf(monkeypatch):
    from app.domains.rag.graph.retrieval import DocumentRetrievalOptions
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

    store = infrastructure.create_hybrid_elasticsearch_store(
        settings=_settings(),
        embedding_model=embedding_model,
        options=DocumentRetrievalOptions(rank_window_size=80),
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
    assert captured["strategy"].hybrid is True
    assert captured["strategy"].rrf == {
        "rank_constant": 60,
        "rank_window_size": 80,
    }
    assert captured["strategy"].text_field == "text"


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


def test_request_scoped_retriever_factory_binds_limits_and_filters():
    from app.domains.rag.graph.retrieval import (
        DocumentRetrievalOptions,
        DocumentRetrievalScope,
    )
    from app.infrastructure.elasticsearch import (
        DocumentHybridRetrieverFactory,
    )

    class FakeStore:
        def __init__(self):
            self.calls = []

        def as_retriever(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(search_kwargs=kwargs["search_kwargs"])

    store = FakeStore()
    factory = DocumentHybridRetrieverFactory(
        store=store,
        options=DocumentRetrievalOptions(
            result_limit=12,
            rank_window_size=60,
        ),
    )

    first = factory.create(
        DocumentRetrievalScope(accessibleBy=["team-a"])
    )
    second = factory.create(
        DocumentRetrievalScope(accessibleBy=["team-b"])
    )

    assert first is not second
    assert first.search_kwargs == {
        "k": 12,
        "fetch_k": 60,
        "filter": [
            {"terms": {"metadata.accessibleBy": ["team-a"]}}
        ],
    }
    assert second.search_kwargs["filter"] == [
        {"terms": {"metadata.accessibleBy": ["team-b"]}}
    ]
    assert first.search_kwargs["filter"] is not second.search_kwargs["filter"]


def test_configured_strategy_generates_match_knn_shared_filters_and_rrf(
    monkeypatch,
):
    from app.domains.rag.graph.retrieval import DocumentRetrievalOptions
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
    infrastructure.create_hybrid_elasticsearch_store(
        settings=_settings(),
        embedding_model=object(),
        options=DocumentRetrievalOptions(rank_window_size=50),
    )
    filters = [
        {"terms": {"metadata.accessibleBy": ["team-a"]}}
    ]

    query = captured["strategy"].es_query(
        query="合同付款周期",
        query_vector=[0.1, 0.2],
        text_field="text",
        vector_field="vector",
        k=10,
        num_candidates=50,
        filter=filters,
    )

    rrf = query["retriever"]["rrf"]
    assert rrf["rank_constant"] == 60
    assert rrf["rank_window_size"] == 50
    standard, knn = rrf["retrievers"]
    assert standard["standard"]["query"] == {
        "bool": {
            "must": [
                {"match": {"text": {"query": "合同付款周期"}}}
            ],
            "filter": filters,
        }
    }
    assert knn["knn"]["field"] == "vector"
    assert knn["knn"]["filter"] == filters
