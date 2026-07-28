"""只暴露文档证据检索的内部 MCP Server。"""

from typing import Protocol

from mcp.server.fastmcp import FastMCP

from app.domains.rag.services import (
    EvidencePackage,
    RetrieveEvidenceRequest,
)

RETRIEVE_EVIDENCE_TOOL = "retrieve_evidence"


class EvidenceService(Protocol):
    async def retrieve_evidence(
        self,
        request: RetrieveEvidenceRequest,
    ) -> EvidencePackage: ...


def create_rag_mcp_server(service: EvidenceService) -> FastMCP:
    """注册唯一无鉴权 Tool，检索逻辑仍由普通 Python 服务持有。"""

    server = FastMCP(
        name="ke-engine-rag",
        host="127.0.0.1",
        port=8002,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    @server.tool(
        name=RETRIEVE_EVIDENCE_TOOL,
        description="从已入库文档中检索可引用证据。",
        structured_output=True,
    )
    async def retrieve_evidence(
        query: str,
        accessibleBy: list[str],
        docIds: list[str] | None = None,
    ) -> EvidencePackage:
        request = RetrieveEvidenceRequest.model_validate(
            {
                "query": query,
                "accessibleBy": accessibleBy,
                "docIds": docIds or [],
            }
        )
        return await service.retrieve_evidence(request)

    return server
