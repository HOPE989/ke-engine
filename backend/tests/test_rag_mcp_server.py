import pytest
from mcp.server.fastmcp.exceptions import ToolError


class RecordingEvidenceService:
    def __init__(self):
        self.calls = []

    async def retrieve_evidence(self, request):
        from app.domains.rag.services import EvidenceItem, EvidencePackage

        self.calls.append(request)
        return EvidencePackage(
            query=request.query,
            selected_retrievers=("DOCUMENT_HYBRID",),
            evidence_items=(
                EvidenceItem(
                    citation_id="doc-1:chunk-1",
                    content="超限货物列车应按规定编组。",
                    doc_id="doc-1",
                    chunk_id="chunk-1",
                    file_name="调度规程.md",
                    rerank_score=0.91,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_rag_mcp_discovers_only_retrieve_evidence():
    from app.services.rag_mcp import create_rag_mcp_server

    tools = await create_rag_mcp_server(
        RecordingEvidenceService()
    ).list_tools()

    assert [tool.name for tool in tools] == ["retrieve_evidence"]
    assert set(tools[0].inputSchema["properties"]) == {
        "query",
        "accessibleBy",
        "docIds",
    }


@pytest.mark.asyncio
async def test_rag_mcp_returns_structured_evidence():
    from app.services.rag_mcp import create_rag_mcp_server

    service = RecordingEvidenceService()
    result = await create_rag_mcp_server(service).call_tool(
        "retrieve_evidence",
        {
            "query": "超限货物列车如何编组？",
            "accessibleBy": ["mock-user"],
        },
    )

    structured = result[1]
    assert structured["query"] == "超限货物列车如何编组？"
    assert structured["selectedRetrievers"] == ["DOCUMENT_HYBRID"]
    assert structured["evidenceItems"][0]["citationId"] == "doc-1:chunk-1"
    assert service.calls[0].accessible_by == ("mock-user",)


@pytest.mark.asyncio
async def test_rag_mcp_rejects_invalid_request_before_application_service():
    from app.services.rag_mcp import create_rag_mcp_server

    service = RecordingEvidenceService()
    server = create_rag_mcp_server(service)

    with pytest.raises(ToolError):
        await server.call_tool(
            "retrieve_evidence",
            {"query": " ", "accessibleBy": []},
        )

    assert service.calls == []
