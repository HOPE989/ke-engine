import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class FakeEvidenceService:
    async def retrieve_evidence(self, request):
        from app.domains.rag.services import EvidenceItem, EvidencePackage

        return EvidencePackage(
            query=request.query,
            standalone_query="煤炭销售合同审批要求",
            evidence_items=(
                EvidenceItem(
                    citation_id="doc-live:chunk-3",
                    content="合同审批须经过业务部门复核。",
                    doc_id="doc-live",
                    chunk_id="chunk-3",
                ),
            ),
        )


@pytest.mark.asyncio
async def test_streamable_http_initializes_discovers_and_calls_tool():
    from app.services.rag_mcp import create_rag_mcp_server

    app = create_rag_mcp_server(
        FakeEvidenceService()
    ).streamable_http_app()
    url = "http://127.0.0.1:8002/mcp"
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8002",
        ) as http_client:
            async with streamable_http_client(
                url,
                http_client=http_client,
            ) as (read_stream, write_stream, _):
                async with ClientSession(
                    read_stream,
                    write_stream,
                ) as session:
                    initialized = await session.initialize()
                    tools = await session.list_tools()
                    result = await session.call_tool(
                        "retrieve_evidence",
                        {
                            "query": "合同审批要求是什么？",
                            "accessibleBy": ["mock-user"],
                        },
                    )

    assert initialized.serverInfo.name == "ke-engine-rag"
    assert [tool.name for tool in tools.tools] == ["retrieve_evidence"]
    assert result.isError is False
    assert result.structuredContent["query"] == "合同审批要求是什么？"
    assert (
        result.structuredContent["standaloneQuery"]
        == "煤炭销售合同审批要求"
    )
    item = result.structuredContent["evidenceItems"][0]
    assert item["citationId"] == "doc-live:chunk-3"
    assert item["content"] == "合同审批须经过业务部门复核。"
    assert item["docId"] == "doc-live"
    assert item["chunkId"] == "chunk-3"
    assert item["fileName"] is None
    assert item["url"] is None
    assert item["rerankScore"] is None
