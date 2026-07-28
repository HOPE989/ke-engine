"""Chat 对文档 RAG 的窄客户端协议。"""

from typing import Protocol

from app.domains.rag.services import (
    EvidencePackage,
    RetrieveEvidenceRequest,
)


class RagClient(Protocol):
    """Chat Graph 依赖的传输无关证据检索能力。"""

    async def retrieve_evidence(
        self,
        request: RetrieveEvidenceRequest,
    ) -> EvidencePackage: ...
