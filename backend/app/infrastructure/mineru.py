"""MinerU miner 工厂与官方/本地 API 调用封装。"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.modules.document.errors import DocumentConversionFailed

logger = logging.getLogger(__name__)


def _format_context(context: dict[str, Any]) -> str:
    parts = []
    for key, value in context.items():
        if value is None or value == "":
            continue
        parts.append(f"{key}={value!r}")
    return ", ".join(parts)


def _raise_conversion_failed(reason: str, **context: Any) -> None:
    details = _format_context(context)
    if details:
        raise DocumentConversionFailed(f"{reason}: {details}")
    raise DocumentConversionFailed(reason)


def _bearer_headers(api_key: str | None) -> dict[str, str] | None:
    """按配置生成 Bearer 认证头，未配置时不发送鉴权头。"""

    if not api_key:
        return None
    return {"Authorization": f"Bearer {api_key}"}


def _require_success_payload(payload: Any) -> dict[str, Any]:
    """校验 MinerU JSON 响应 envelope 并返回 data。"""

    if not isinstance(payload, dict) or payload.get("code") != 0:
        _raise_conversion_failed(
            "MinerU API returned unsuccessful payload",
            code=payload.get("code") if isinstance(payload, dict) else None,
            msg=payload.get("msg") if isinstance(payload, dict) else None,
            trace_id=payload.get("trace_id") if isinstance(payload, dict) else None,
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        _raise_conversion_failed(
            "MinerU API payload missing data",
            code=payload.get("code"),
            msg=payload.get("msg"),
            trace_id=payload.get("trace_id"),
        )
    return data


@dataclass(slots=True)
class LocalMiner:
    """调用本地部署的 MinerU `/file_parse` 同步 ZIP 接口。"""

    http_client: Any
    api_key: str | None = None

    async def request_zip(self, *, filename: str, content: bytes) -> bytes:
        """提交文档内容并返回 MinerU ZIP bytes。"""

        request_kwargs: dict[str, Any] = {
            "files": {"files": (filename, content)},
            "data": {
                "output_format": "zip",
                "return_images": True,
            },
        }
        headers = _bearer_headers(self.api_key)
        if headers is not None:
            request_kwargs["headers"] = headers

        try:
            response = await self.http_client.post("/file_parse", **request_kwargs)
            response.raise_for_status()
        except Exception as exc:
            raise DocumentConversionFailed() from exc
        return response.content

    async def aclose(self) -> None:
        """关闭底层 HTTP client。"""

        await self.http_client.aclose()


@dataclass(slots=True)
class OfficialMiner:
    """调用 MinerU 官方精准解析 API，并统一产出 ZIP bytes。"""

    http_client: Any
    api_key: str
    model_version: str
    poll_interval_seconds: float
    poll_timeout_seconds: float

    async def request_zip(self, *, filename: str, content: bytes) -> bytes:
        """上传本地文件，轮询解析任务，下载并返回结果 ZIP。"""

        try:
            batch_id, upload_url = await self._request_upload_url(filename)
            await self._upload_file(upload_url=upload_url, content=content)
            full_zip_url = await self._poll_full_zip_url(batch_id)
            return await self._download_zip(full_zip_url)
        except DocumentConversionFailed:
            raise
        except Exception as exc:
            raise DocumentConversionFailed() from exc

    async def _request_upload_url(self, filename: str) -> tuple[str, str]:
        response = await self.http_client.post(
            "/api/v4/file-urls/batch",
            json={
                "files": [{"name": filename}],
                "model_version": self.model_version,
            },
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        data = _require_success_payload(response.json())
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls")
        if not isinstance(batch_id, str) or not isinstance(file_urls, list) or not file_urls:
            _raise_conversion_failed("MinerU upload URL response is invalid", batch_id=batch_id)
        upload_url = file_urls[0]
        if not isinstance(upload_url, str) or not upload_url:
            _raise_conversion_failed("MinerU upload URL is invalid", batch_id=batch_id)
        return batch_id, upload_url

    async def _upload_file(self, *, upload_url: str, content: bytes) -> None:
        response = await self.http_client.put(upload_url, data=content)
        response.raise_for_status()

    async def _poll_full_zip_url(self, batch_id: str) -> str:
        deadline = time.monotonic() + self.poll_timeout_seconds
        while True:
            result = await self._get_batch_result(batch_id)
            state = result.get("state")
            log_context = {
                "batch_id": result.get("_batch_id"),
                "trace_id": result.get("_trace_id"),
                "file_name": result.get("file_name"),
                "state": state,
                "err_msg": result.get("err_msg"),
            }
            logger.info("mineru official batch result polled", extra=log_context)
            if state == "done":
                full_zip_url = result.get("full_zip_url")
                if isinstance(full_zip_url, str) and full_zip_url:
                    return full_zip_url
                logger.error("mineru official task completed without zip url", extra=log_context)
                _raise_conversion_failed(
                    "MinerU task completed without full_zip_url",
                    batch_id=result.get("_batch_id"),
                    trace_id=result.get("_trace_id"),
                    file_name=result.get("file_name"),
                    state=state,
                    err_msg=result.get("err_msg"),
                )
            if state == "failed":
                logger.error("mineru official task failed", extra=log_context)
                _raise_conversion_failed(
                    "MinerU task failed",
                    batch_id=result.get("_batch_id"),
                    trace_id=result.get("_trace_id"),
                    file_name=result.get("file_name"),
                    state=state,
                    err_msg=result.get("err_msg"),
                )
            if time.monotonic() >= deadline:
                logger.error(
                    "mineru official task polling timed out",
                    extra={**log_context, "timeout_seconds": self.poll_timeout_seconds},
                )
                _raise_conversion_failed(
                    "MinerU task polling timed out",
                    batch_id=result.get("_batch_id"),
                    trace_id=result.get("_trace_id"),
                    file_name=result.get("file_name"),
                    state=state,
                    err_msg=result.get("err_msg"),
                    timeout_seconds=self.poll_timeout_seconds,
                )
            await asyncio.sleep(self.poll_interval_seconds)

    async def _get_batch_result(self, batch_id: str) -> dict[str, Any]:
        response = await self.http_client.get(
            f"/api/v4/extract-results/batch/{batch_id}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        payload = response.json()
        data = _require_success_payload(payload)
        extract_result = data.get("extract_result")
        if not isinstance(extract_result, list) or not extract_result:
            _raise_conversion_failed("MinerU batch result is empty", batch_id=batch_id)
        first_result = extract_result[0]
        if not isinstance(first_result, dict):
            _raise_conversion_failed("MinerU batch result item is invalid", batch_id=batch_id)
        return {
            **first_result,
            "_batch_id": data.get("batch_id") or batch_id,
            "_trace_id": payload.get("trace_id"),
        }

    async def _download_zip(self, full_zip_url: str) -> bytes:
        response = await self.http_client.get(full_zip_url)
        response.raise_for_status()
        return response.content

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def aclose(self) -> None:
        """关闭底层 HTTP client。"""

        await self.http_client.aclose()


def create_mineru_client(settings: Any) -> LocalMiner | OfficialMiner:
    """按 `MINERU_PROVIDER` 创建本地或官方 MinerU miner。"""

    provider = str(getattr(settings, "mineru_provider", "local")).strip().lower()
    if provider not in {"local", "official"}:
        raise ValueError("MINERU_PROVIDER must be 'local' or 'official'")

    api_key = getattr(settings, "mineru_api_key", None)
    if provider == "official" and not api_key:
        raise ValueError("MINERU_API_KEY is required when MINERU_PROVIDER=official")

    http_client = httpx.AsyncClient(
        base_url=getattr(settings, "mineru_base_url"),
        timeout=getattr(settings, "mineru_timeout_seconds"),
    )

    if provider == "local":
        return LocalMiner(http_client=http_client, api_key=api_key)

    return OfficialMiner(
        http_client=http_client,
        api_key=api_key,
        model_version=getattr(settings, "mineru_model_version", "vlm"),
        poll_interval_seconds=getattr(settings, "mineru_poll_interval_seconds", 2),
        poll_timeout_seconds=getattr(settings, "mineru_poll_timeout_seconds", 300),
    )
