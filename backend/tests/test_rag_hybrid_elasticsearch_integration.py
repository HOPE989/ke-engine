"""显式运行的开源版 Elasticsearch 自定义 Hybrid/RRF 集成测试。

运行方式（PowerShell）：

    $env:RUN_ELASTICSEARCH_INTEGRATION = "1"
    $env:ELASTICSEARCH_URL = "http://127.0.0.1:9200"
    uv run pytest tests/test_rag_hybrid_elasticsearch_integration.py -q

目标集群应使用 Basic License；测试不调用企业版原生 RRF Retriever。
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
    create_document_retrieval_store,
    create_elasticsearch_client,
    ensure_vector_index,
)
from app.infrastructure.rerank import RerankResult, RerankScore


pytestmark = pytest.mark.integration

if os.getenv("RUN_ELASTICSEARCH_INTEGRATION") != "1":
    pytest.skip(
        "set RUN_ELASTICSEARCH_INTEGRATION=1 to run Elasticsearch tests",
        allow_module_level=True,
    )


class _DeterministicReranker:
    async def rerank(self, query, documents):
        del query
        return RerankResult(
            request_id="integration-fake-rerank",
            scores=tuple(
                RerankScore(index=index, relevance_score=1.0)
                for index in range(len(documents))
            ),
        )


@pytest.mark.asyncio
async def test_custom_hybrid_retrieval_on_basic_elasticsearch():
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
        candidate_limit=20,
    )
    index_created = False

    try:
        ensure_vector_index(
            client,
            index_name=index_name,
            embedding_dimensions=dimensions,
        )
        index_created = True
        license_info = client.license.get()
        assert license_info["license"]["type"] == "basic"
        assert license_info["license"]["status"] == "active"

        store = create_document_retrieval_store(
            settings=settings,
            embedding_model=DeterministicFakeEmbedding(
                size=dimensions
            ),
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
            client=client,
            store=store,
            index_name=index_name,
            options=options,
            reranker=_DeterministicReranker(),
        )

        team_a_results = await factory.create(
            DocumentRetrievalScope(accessibleBy=["team-a"])
        ).ainvoke("铁路运输合同付款周期")
        only_one_doc = await factory.create(
            DocumentRetrievalScope(
                accessibleBy=["team-a"],
                docIds=["doc-team-a"],
            )
        ).ainvoke("铁路运输合同付款周期")
        empty = await factory.create(
            DocumentRetrievalScope(
                accessibleBy=["team-a"],
                docIds=["missing-doc"],
            )
        ).ainvoke("铁路运输合同付款周期")

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
