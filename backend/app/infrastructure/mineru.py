"""MinerU miner 工厂与官方/本地 API 调用封装。"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.modules.document.errors import DocumentConversionFailed


def _bearer_headers(api_key: str | None) -> dict[str, str] | None:
    """按配置生成 Bearer 认证头，未配置时不发送鉴权头。"""

    if not api_key:
        return None
    return {"Authorization": f"Bearer {api_key}"}


def _require_success_payload(payload: Any) -> dict[str, Any]:
    """校验 MinerU JSON 响应 envelope 并返回 data。"""

    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise DocumentConversionFailed()
    data = payload.get("data")
    if not isinstance(data, dict):
        raise DocumentConversionFailed()
    return data


@dataclass(slots=True)
class LocalMiner:
    """调用本地部署的 MinerU `/file_parse` 同步 ZIP 接口。"""

    http_client: Any
    api_key: str | None = None

    async def request_zip(self, *, filename: str, content: bytes) -> bytes:
        """提交 PDF 内容并返回 MinerU ZIP bytes。"""

        request_kwargs: dict[str, Any] = {
            "files": {"file": (filename, content, "application/pdf")},
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
            raise DocumentConversionFailed()
        upload_url = file_urls[0]
        if not isinstance(upload_url, str) or not upload_url:
            raise DocumentConversionFailed()
        return batch_id, upload_url

    async def _upload_file(self, *, upload_url: str, content: bytes) -> None:
        response = await self.http_client.put(upload_url, data=content)
        response.raise_for_status()

    async def _poll_full_zip_url(self, batch_id: str) -> str:
        deadline = time.monotonic() + self.poll_timeout_seconds
        while True:
            result = await self._get_batch_result(batch_id)
            state = result.get("state")
            if state == "done":
                full_zip_url = result.get("full_zip_url")
                if isinstance(full_zip_url, str) and full_zip_url:
                    return full_zip_url
                raise DocumentConversionFailed()
            if state == "failed":
                raise DocumentConversionFailed()
            if time.monotonic() >= deadline:
                raise DocumentConversionFailed()
            await asyncio.sleep(self.poll_interval_seconds)

    async def _get_batch_result(self, batch_id: str) -> dict[str, Any]:
        response = await self.http_client.get(
            f"/api/v4/extract-results/batch/{batch_id}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        data = _require_success_payload(response.json())
        extract_result = data.get("extract_result")
        if not isinstance(extract_result, list) or not extract_result:
            raise DocumentConversionFailed()
        first_result = extract_result[0]
        if not isinstance(first_result, dict):
            raise DocumentConversionFailed()
        return first_result

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
