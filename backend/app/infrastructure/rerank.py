"""百炼 Qwen3 Rerank 的异步基础设施客户端。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Sequence
from urllib.parse import urlsplit, urlunsplit

import httpx

QWEN3_RERANK_MODEL = "qwen3-rerank"
QWEN3_RERANK_INSTRUCTION = (
    "Given a web search query, retrieve relevant passages that answer "
    "the query."
)
QWEN3_RERANK_MIN_SCORE = 0.6


@dataclass(frozen=True, slots=True)
class RerankScore:
    index: int
    relevance_score: float


@dataclass(frozen=True, slots=True)
class RerankResult:
    request_id: str
    scores: tuple[RerankScore, ...]


class BailianQwen3Reranker:
    """调用百炼 Workspace 下的 Qwen3 Rerank API。"""

    def __init__(
        self,
        *,
        http_client: Any,
        openai_base_url: str,
        api_key: str,
        timeout_seconds: float,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("OPENAI_API_KEY is required for Rerank")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._http_client = http_client
        self._endpoint = derive_bailian_rerank_endpoint(
            openai_base_url
        )
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds

    async def rerank(
        self,
        query: str,
        documents: Sequence[str],
    ) -> RerankResult:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Rerank query must be non-blank")
        if not documents:
            raise ValueError("Rerank documents must not be empty")
        if any(
            not isinstance(document, str) or not document.strip()
            for document in documents
        ):
            raise ValueError("Rerank documents must be non-blank strings")

        response = await self._http_client.post(
            self._endpoint,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": QWEN3_RERANK_MODEL,
                "query": query.strip(),
                "documents": list(documents),
                "top_n": len(documents),
                "instruct": QWEN3_RERANK_INSTRUCTION,
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return _parse_rerank_response(
            response.json(),
            document_count=len(documents),
        )


def derive_bailian_rerank_endpoint(openai_base_url: str) -> str:
    """从现有 OpenAI 兼容地址提取 Workspace origin。"""

    if (
        not isinstance(openai_base_url, str)
        or not openai_base_url.strip()
    ):
        raise ValueError("OPENAI_BASE_URL is required for Rerank")
    parsed = urlsplit(openai_base_url.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("OPENAI_BASE_URL must be an HTTP(S) origin")
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            "/compatible-api/v1/reranks",
            "",
            "",
        )
    )


@lru_cache(maxsize=1)
def get_shared_rerank_http_client() -> httpx.AsyncClient:
    """返回进程内共享的异步 HTTP 长连接客户端。"""

    return httpx.AsyncClient()


def _parse_rerank_response(
    payload: Any,
    *,
    document_count: int,
) -> RerankResult:
    if not isinstance(payload, dict):
        raise ValueError("Rerank response must be an object")
    request_id = payload.get("id")
    results = payload.get("results")
    if (
        not isinstance(request_id, str)
        or not request_id.strip()
        or not isinstance(results, list)
    ):
        raise ValueError("Rerank response is missing required fields")

    scores: list[RerankScore] = []
    indexes: set[int] = set()
    for item in results:
        if not isinstance(item, dict):
            raise ValueError("Rerank result must be an object")
        index = item.get("index")
        score = item.get("relevance_score")
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or index < 0
            or index >= document_count
            or index in indexes
        ):
            raise ValueError("Rerank result has invalid index")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
            or not 0 <= float(score) <= 1
        ):
            raise ValueError("Rerank result has invalid relevance_score")
        indexes.add(index)
        scores.append(
            RerankScore(
                index=index,
                relevance_score=float(score),
            )
        )

    if indexes != set(range(document_count)):
        raise ValueError("Rerank response does not score every document")
    return RerankResult(
        request_id=request_id.strip(),
        scores=tuple(scores),
    )
