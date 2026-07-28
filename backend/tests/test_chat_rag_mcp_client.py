from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest


def _request():
    from app.domains.rag.services import RetrieveEvidenceRequest

    return RetrieveEvidenceRequest.model_validate(
        {
            "query": "调度规程有哪些要求？",
            "accessibleBy": ["alice"],
            "conversationContext": [
                {"role": "assistant", "content": "正在讨论铁路运输。"}
            ],
            "businessIntent": "POLICY_RULE_QA",
        }
    )


@pytest.mark.asyncio
async def test_mcp_rag_client_serializes_request_and_parses_structured_result(
    monkeypatch,
):
    from app.infrastructure import rag_mcp_client as rag_mcp

    calls = []
    result = SimpleNamespace(
        isError=False,
        structuredContent={
            "query": "调度规程有哪些要求？",
            "standaloneQuery": "铁路调度规程要求",
            "evidenceItems": [
                {
                    "citationId": "doc-1:chunk-1",
                    "content": "列车编组应符合规程。",
                    "docId": "doc-1",
                    "chunkId": "chunk-1",
                    "fileName": "调度规程.md",
                }
            ],
        },
    )

    class FakeSession:
        def __init__(self, read_stream, write_stream):
            calls.append(("session", read_stream, write_stream))

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def initialize(self):
            calls.append("initialize")

        async def call_tool(self, name, arguments):
            calls.append(("call", name, arguments))
            return result

    @asynccontextmanager
    async def fake_transport(url):
        calls.append(("transport", url))
        yield "read", "write", lambda: None

    monkeypatch.setattr(rag_mcp, "ClientSession", FakeSession)
    monkeypatch.setattr(
        rag_mcp,
        "streamable_http_client",
        fake_transport,
    )

    package = await rag_mcp.McpRagClient(
        "http://127.0.0.1:8002/mcp"
    ).retrieve_evidence(_request())

    assert package.standalone_query == "铁路调度规程要求"
    assert package.evidence_items[0].citation_id == "doc-1:chunk-1"
    assert calls[-1] == (
        "call",
        "retrieve_evidence",
        {
            "query": "调度规程有哪些要求？",
            "accessibleBy": ["alice"],
            "docIds": [],
            "conversationContext": [
                {"role": "assistant", "content": "正在讨论铁路运输。"}
            ],
            "businessIntent": "POLICY_RULE_QA",
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(isError=True, structuredContent=None),
        SimpleNamespace(
            isError=False,
            structuredContent={"query": "missing contract fields"},
        ),
    ],
)
async def test_mcp_rag_client_propagates_tool_or_contract_failure(
    monkeypatch,
    result,
):
    from app.infrastructure import rag_mcp_client as rag_mcp

    class FakeSession:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def initialize(self):
            return None

        async def call_tool(self, name, arguments):
            return result

    @asynccontextmanager
    async def fake_transport(url):
        yield "read", "write", lambda: None

    monkeypatch.setattr(rag_mcp, "ClientSession", FakeSession)
    monkeypatch.setattr(
        rag_mcp,
        "streamable_http_client",
        fake_transport,
    )

    with pytest.raises(Exception):
        await rag_mcp.McpRagClient("http://rag/mcp").retrieve_evidence(
            _request()
        )
