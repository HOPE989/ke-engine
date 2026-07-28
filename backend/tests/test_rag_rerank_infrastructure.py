import json

import httpx
import pytest


@pytest.mark.asyncio
async def test_qwen3_reranker_builds_request_and_parses_scores():
    from app.infrastructure.rerank import (
        BailianQwen3Reranker,
        QWEN3_RERANK_INSTRUCTION,
    )

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "rerank-request-1",
                "results": [
                    {"index": 1, "relevance_score": 0.6},
                    {"index": 0, "relevance_score": 0.91},
                ],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http_client:
        reranker = BailianQwen3Reranker(
            http_client=http_client,
            openai_base_url=(
                "https://workspace.example.com/compatible-mode/v1"
            ),
            api_key="test-key",
            timeout_seconds=10,
        )

        result = await reranker.rerank(
            "合同付款周期",
            ["父分段一", "父分段二"],
        )

    assert captured == {
        "url": (
            "https://workspace.example.com/"
            "compatible-api/v1/reranks"
        ),
        "authorization": "Bearer test-key",
        "payload": {
            "model": "qwen3-rerank",
            "query": "合同付款周期",
            "documents": ["父分段一", "父分段二"],
            "top_n": 2,
            "instruct": QWEN3_RERANK_INSTRUCTION,
        },
    }
    assert result.request_id == "rerank-request-1"
    assert [
        (score.index, score.relevance_score)
        for score in result.scores
    ] == [(1, 0.6), (0, 0.91)]


@pytest.mark.asyncio
async def test_qwen3_reranker_propagates_provider_error():
    from app.infrastructure.rerank import BailianQwen3Reranker

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                503,
                request=request,
                json={"message": "unavailable"},
            )
        )
    ) as http_client:
        reranker = BailianQwen3Reranker(
            http_client=http_client,
            openai_base_url=(
                "https://workspace.example.com/compatible-mode/v1"
            ),
            api_key="test-key",
            timeout_seconds=10,
        )

        with pytest.raises(httpx.HTTPStatusError):
            await reranker.rerank("query", ["document"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"results": [{"index": 0, "relevance_score": 0.8}]},
        {"id": "request-1", "results": [{"relevance_score": 0.8}]},
        {"id": "request-1", "results": [{"index": 0}]},
        {
            "id": "request-1",
            "results": [{"index": 1, "relevance_score": 0.8}],
        },
        {"id": "request-1", "results": []},
    ],
)
async def test_qwen3_reranker_rejects_malformed_required_fields(
    payload,
):
    from app.infrastructure.rerank import BailianQwen3Reranker

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                request=request,
                json=payload,
            )
        )
    ) as http_client:
        reranker = BailianQwen3Reranker(
            http_client=http_client,
            openai_base_url=(
                "https://workspace.example.com/compatible-mode/v1"
            ),
            api_key="test-key",
            timeout_seconds=10,
        )

        with pytest.raises(ValueError, match="Rerank"):
            await reranker.rerank("query", ["document"])


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "workspace.example.com/compatible-mode/v1",
        "https://user:pass@workspace.example.com/v1",
    ],
)
def test_bailian_rerank_endpoint_rejects_invalid_base_url(base_url):
    from app.infrastructure.rerank import (
        derive_bailian_rerank_endpoint,
    )

    with pytest.raises(ValueError, match="OPENAI_BASE_URL"):
        derive_bailian_rerank_endpoint(base_url)
