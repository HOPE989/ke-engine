"""基于官方 MCP SDK 的 Chat RAG Client 适配器。"""

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.domains.rag.services import (
    EvidencePackage,
    RetrieveEvidenceRequest,
)
from app.services.rag_mcp import RETRIEVE_EVIDENCE_TOOL


class McpRagClient:
    """每次调用建立一个最小 Streamable HTTP MCP 会话。"""

    def __init__(self, url: str) -> None:
        self._url = url

    async def retrieve_evidence(
        self,
        request: RetrieveEvidenceRequest,
    ) -> EvidencePackage:
        async with streamable_http_client(self._url) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(
                    RETRIEVE_EVIDENCE_TOOL,
                    request.model_dump(
                        mode="json",
                        by_alias=True,
                        exclude_none=True,
                    ),
                )
        if result.isError or result.structuredContent is None:
            raise RuntimeError("RAG MCP retrieve_evidence failed")
        return EvidencePackage.model_validate(result.structuredContent)
