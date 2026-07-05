from types import SimpleNamespace

import pytest


def _settings(**overrides):
    values = {
        "openai_api_key": "test-key",
        "openai_base_url": "https://openai.example.com/v1",
        "elasticsearch_url": "http://elasticsearch.example:9200",
        "elasticsearch_index": "custom-vector-index",
        "embedding_dimensions": 1536,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _segment(**overrides):
    values = {
        "id": 9001,
        "chunk_id": "10001",
        "text": "segment text",
        "metadata_": {
            "docId": "42",
            "chunkId": "10001",
            "fileName": "guide.md",
            "accessibleBy": "team-a",
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_embedding_model_uses_fixed_model_chunk_size_and_configured_dimensions(monkeypatch):
    from app.modules.document import vector_store

    captured = {}

    class FakeOpenAIEmbeddings:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(vector_store, "OpenAIEmbeddings", FakeOpenAIEmbeddings)

    model = vector_store.create_embedding_model(_settings(embedding_dimensions=2048))

    assert isinstance(model, FakeOpenAIEmbeddings)
    assert captured == {
        "api_key": "test-key",
        "base_url": "https://openai.example.com/v1",
        "model": "text-embedding-v4",
        "chunk_size": 9,
        "dimensions": 2048,
        "check_embedding_ctx_length": False,
    }


def test_elasticsearch_store_uses_configured_index_and_dimensions(monkeypatch):
    from app.modules.document import vector_store

    captured = {}
    embedding_model = object()

    class FakeElasticsearchStore:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(vector_store, "ElasticsearchStore", FakeElasticsearchStore)

    store = vector_store.create_elasticsearch_store(
        settings=_settings(),
        embedding_model=embedding_model,
    )

    assert isinstance(store, FakeElasticsearchStore)
    assert captured == {
        "index_name": "custom-vector-index",
        "es_url": "http://elasticsearch.example:9200",
        "embedding": embedding_model,
        "query_field": "text",
        "vector_query_field": "vector",
        "num_dimensions": 1536,
    }


@pytest.mark.asyncio
async def test_adapter_stores_segment_text_as_page_content_and_metadata_separately():
    from app.modules.document.vector_store import ElasticsearchVectorStoreAdapter

    class FakeStore:
        def __init__(self):
            self.documents = []

        async def aadd_documents(self, documents):
            self.documents = documents
            return ["es-id-1", "es-id-2"]

    store = FakeStore()
    segments = [
        _segment(text="first", metadata_={"docId": "42", "chunkId": "10001"}),
        _segment(text="second", metadata_={"docId": "42", "chunkId": "10002"}),
    ]

    ids = await ElasticsearchVectorStoreAdapter(store=store).add_segments(segments)

    assert ids == ["es-id-1", "es-id-2"]
    assert [document.page_content for document in store.documents] == ["first", "second"]
    assert [document.metadata for document in store.documents] == [
        {"docId": "42", "chunkId": "10001"},
        {"docId": "42", "chunkId": "10002"},
    ]
    assert all("text" not in document.metadata for document in store.documents)


@pytest.mark.asyncio
async def test_adapter_preserves_returned_ids_order_and_rejects_count_mismatch():
    from app.modules.document import vector_store
    from app.modules.document.vector_store import ElasticsearchVectorStoreAdapter

    class FakeStore:
        async def aadd_documents(self, documents):
            return ["only-one-id"]

    with pytest.raises(vector_store.VectorStoreIdCountMismatch):
        await ElasticsearchVectorStoreAdapter(store=FakeStore()).add_segments(
            [
                _segment(chunk_id="10001"),
                _segment(chunk_id="10002"),
            ]
        )


@pytest.mark.asyncio
async def test_adapter_can_delete_vectors_by_ids_and_metadata_doc_id():
    from app.modules.document.vector_store import ElasticsearchVectorStoreAdapter

    class FakeStore:
        def __init__(self):
            self.deleted_ids = []

        async def adelete(self, ids=None, **kwargs):
            self.deleted_ids.append(ids)
            return True

    class FakeClient:
        def __init__(self):
            self.delete_by_query_calls = []

        async def delete_by_query(self, **kwargs):
            self.delete_by_query_calls.append(kwargs)
            return {"deleted": 2}

    store = FakeStore()
    client = FakeClient()
    adapter = ElasticsearchVectorStoreAdapter(
        store=store,
        client=client,
        index_name="custom-vector-index",
    )

    await adapter.delete_by_ids(["es-id-1", "es-id-2"])
    await adapter.delete_by_doc_id(42)

    assert store.deleted_ids == [["es-id-1", "es-id-2"]]
    assert client.delete_by_query_calls == [
        {
            "index": "custom-vector-index",
            "query": {"term": {"metadata.docId": "42"}},
            "conflicts": "proceed",
            "refresh": True,
        }
    ]


def test_ensure_vector_index_creates_mapping_with_configured_dimensions():
    from app.modules.document import vector_store

    class FakeIndices:
        def __init__(self):
            self.created = []

        def exists(self, *, index):
            return False

        def create(self, **kwargs):
            self.created.append(kwargs)

    indices = FakeIndices()
    client = SimpleNamespace(indices=indices)

    vector_store.ensure_vector_index(
        client,
        index_name="custom-vector-index",
        embedding_dimensions=1536,
    )

    assert indices.created == [
        {
            "index": "custom-vector-index",
            "mappings": {
                "properties": {
                    "text": {"type": "text"},
                    "vector": {"type": "dense_vector", "dims": 1536},
                    "metadata": {"type": "object", "enabled": True},
                }
            },
        }
    ]


def test_ensure_vector_index_rejects_dimension_mismatch():
    from app.modules.document import vector_store

    class FakeIndices:
        def exists(self, *, index):
            return True

        def get_mapping(self, *, index):
            return {
                "custom-vector-index": {
                    "mappings": {
                        "properties": {
                            "vector": {"type": "dense_vector", "dims": 512},
                        }
                    }
                }
            }

    client = SimpleNamespace(indices=FakeIndices())

    with pytest.raises(vector_store.VectorIndexDimensionMismatch):
        vector_store.ensure_vector_index(
            client,
            index_name="custom-vector-index",
            embedding_dimensions=1536,
        )
