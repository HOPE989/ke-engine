"""显式运行的 Elasticsearch 原生 Hybrid/RRF 集成测试。

运行方式（PowerShell）：

    $env:RUN_ELASTICSEARCH_INTEGRATION = "1"
    $env:ELASTICSEARCH_URL = "http://127.0.0.1:9200"
    uv run pytest tests/test_rag_hybrid_elasticsearch_integration.py -q

目标集群必须支持 Elasticsearch 原生 RRF retriever 及其许可证要求。
测试使用唯一临时索引并在结束时删除；生产旧索引若缺少 keyword
过滤字段，部署前仍须重建或 reindex。
"""

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from app.domains.rag.graph.retrieval import (
    DocumentRetrievalOptions,
    DocumentRetrievalScope,
)
from app.infrastructure.elasticsearch import (
    DocumentHybridRetrieverFactory,
    create_elasticsearch_client,
    create_hybrid_elasticsearch_store,
    ensure_vector_index,
)


pytestmark = pytest.mark.integration

if os.getenv("RUN_ELASTICSEARCH_INTEGRATION") != "1":
    pytest.skip(
        "set RUN_ELASTICSEARCH_INTEGRATION=1 to run Elasticsearch tests",
        allow_module_level=True,
    )


def test_native_hybrid_retrieval_filters_rrf_empty_and_mapping():
    dimensions = 32
    index_name = f"ke-engine-hybrid-test-{uuid4().hex}"
    settings = SimpleNamespace(
        elasticsearch_url=os.getenv(
            "ELASTICSEARCH_URL",
            "http://127.0.0.1:9200",
        ),
        elasticsearch_index=index_name,
        embedding_dimensions=dimensions,
    )
    client = create_elasticsearch_client(settings)
    options = DocumentRetrievalOptions(
        result_limit=5,
        rank_window_size=20,
    )
    index_created = False

    try:
        ensure_vector_index(
            client,
            index_name=index_name,
            embedding_dimensions=dimensions,
        )
        index_created = True
        store = create_hybrid_elasticsearch_store(
            settings=settings,
            embedding_model=DeterministicFakeEmbedding(
                size=dimensions
            ),
            options=options,
            client=client,
        )
        store.add_documents(
            [
                Document(
                    page_content="铁路运输合同付款周期为三十天",
                    metadata={
                        "chunkId": "chunk-team-a",
                        "docId": "doc-team-a",
                        "accessibleBy": "team-a",
                        "fileName": "team-a-contract.md",
                    },
                ),
                Document(
                    page_content="铁路运输合同付款周期为六十天",
                    metadata={
                        "chunkId": "chunk-team-b",
                        "docId": "doc-team-b",
                        "accessibleBy": "team-b",
                        "fileName": "team-b-contract.md",
                    },
                ),
                Document(
                    page_content="设备维护计划与备件库存",
                    metadata={
                        "chunkId": "chunk-maintenance",
                        "docId": "doc-maintenance",
                        "accessibleBy": "team-a",
                        "fileName": "maintenance.md",
                    },
                ),
            ],
            refresh_indices=True,
        )
        factory = DocumentHybridRetrieverFactory(
            store=store,
            options=options,
        )

        team_a_results = factory.create(
            DocumentRetrievalScope(accessibleBy=["team-a"])
        ).invoke("铁路运输合同付款周期")
        only_one_doc = factory.create(
            DocumentRetrievalScope(
                accessibleBy=["team-a"],
                docIds=["doc-team-a"],
            )
        ).invoke("铁路运输合同付款周期")
        empty = factory.create(
            DocumentRetrievalScope(
                accessibleBy=["team-a"],
                docIds=["missing-doc"],
            )
        ).invoke("铁路运输合同付款周期")

        assert team_a_results
        assert {
            result.metadata["accessibleBy"]
            for result in team_a_results
        } == {"team-a"}
        assert [
            result.metadata["docId"] for result in only_one_doc
        ] == ["doc-team-a"]
        assert empty == []

        ensure_vector_index(
            client,
            index_name=index_name,
            embedding_dimensions=dimensions,
        )
    finally:
        if index_created:
            client.indices.delete(
                index=index_name,
                ignore_unavailable=True,
            )
        client.close()
