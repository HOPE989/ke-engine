from types import SimpleNamespace

import pytest

from app.modules.document.errors import DocumentConversionFailed


def _settings(**overrides):
    values = {
        "mineru_provider": "local",
        "mineru_base_url": "https://mineru.example.com",
        "mineru_api_key": None,
        "mineru_model_version": "vlm",
        "mineru_poll_interval_seconds": 0,
        "mineru_poll_timeout_seconds": 1,
        "mineru_timeout_seconds": 30,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeResponse:
    def __init__(self, *, content=b"", json_data=None, status_error=None):
        self.content = content
        self._json_data = json_data
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error is not None:
            raise self._status_error

    def json(self):
        return self._json_data


class FakeHttpClient:
    def __init__(self, *, base_url=None, timeout=None, responses=None):
        self.base_url = base_url
        self.timeout = timeout
        self.responses = list(responses or [])
        self.calls = []
        self.closed = False

    def _response(self):
        if not self.responses:
            raise AssertionError("unexpected HTTP call")
        return self.responses.pop(0)

    async def post(self, path, **kwargs):
        self.calls.append(("post", path, kwargs))
        return self._response()

    async def put(self, path, **kwargs):
        self.calls.append(("put", path, kwargs))
        return self._response()

    async def get(self, path, **kwargs):
        self.calls.append(("get", path, kwargs))
        return self._response()

    async def aclose(self):
        self.closed = True


def test_mineru_factory_returns_local_miner_by_default(monkeypatch):
    from app.infrastructure import mineru as mineru_infra

    created_clients = []

    class FakeAsyncClient(FakeHttpClient):
        def __init__(self, *, base_url, timeout):
            super().__init__(base_url=base_url, timeout=timeout)
            created_clients.append(self)

    monkeypatch.setattr(mineru_infra.httpx, "AsyncClient", FakeAsyncClient)

    miner = mineru_infra.create_mineru_client(_settings())

    assert isinstance(miner, mineru_infra.LocalMiner)
    assert created_clients == [miner.http_client]
    assert miner.http_client.base_url == "https://mineru.example.com"
    assert miner.http_client.timeout == 30


def test_mineru_factory_returns_official_miner_for_official_provider(monkeypatch):
    from app.infrastructure import mineru as mineru_infra

    created_clients = []

    class FakeAsyncClient(FakeHttpClient):
        def __init__(self, *, base_url, timeout):
            super().__init__(base_url=base_url, timeout=timeout)
            created_clients.append(self)

    monkeypatch.setattr(mineru_infra.httpx, "AsyncClient", FakeAsyncClient)

    miner = mineru_infra.create_mineru_client(
        _settings(mineru_provider="official", mineru_api_key="secret-token")
    )

    assert isinstance(miner, mineru_infra.OfficialMiner)
    assert created_clients == [miner.http_client]
    assert miner.http_client.base_url == "https://mineru.example.com"
    assert miner.api_key == "secret-token"


def test_official_miner_requires_api_key():
    from app.infrastructure import mineru as mineru_infra

    with pytest.raises(ValueError, match="MINERU_API_KEY"):
        mineru_infra.create_mineru_client(_settings(mineru_provider="official"))


@pytest.mark.asyncio
async def test_local_miner_requests_file_parse_zip_and_sends_optional_bearer_token():
    from app.infrastructure import mineru as mineru_infra

    http_client = FakeHttpClient(
        responses=[FakeResponse(content=b"zip-bytes")],
    )
    miner = mineru_infra.LocalMiner(http_client=http_client, api_key="local-token")

    result = await miner.request_zip(filename="guide.pdf", content=b"%PDF-1.7")

    assert result == b"zip-bytes"
    assert http_client.calls == [
        (
            "post",
            "/file_parse",
            {
                "files": {"file": ("guide.pdf", b"%PDF-1.7", "application/pdf")},
                "data": {"output_format": "zip", "return_images": True},
                "headers": {"Authorization": "Bearer local-token"},
            },
        )
    ]


@pytest.mark.asyncio
async def test_official_miner_uploads_file_polls_done_and_downloads_zip():
    from app.infrastructure import mineru as mineru_infra

    http_client = FakeHttpClient(
        responses=[
            FakeResponse(
                json_data={
                    "code": 0,
                    "data": {
                        "batch_id": "batch-1",
                        "file_urls": ["https://oss.example/upload"],
                    },
                }
            ),
            FakeResponse(),
            FakeResponse(
                json_data={
                    "code": 0,
                    "data": {
                        "batch_id": "batch-1",
                        "extract_result": [
                            {
                                "file_name": "guide.pdf",
                                "state": "done",
                                "full_zip_url": "https://cdn.example/result.zip",
                            }
                        ],
                    },
                }
            ),
            FakeResponse(content=b"zip-bytes"),
        ],
    )
    miner = mineru_infra.OfficialMiner(
        http_client=http_client,
        api_key="official-token",
        model_version="vlm",
        poll_interval_seconds=0,
        poll_timeout_seconds=1,
    )

    result = await miner.request_zip(filename="guide.pdf", content=b"%PDF-1.7")

    assert result == b"zip-bytes"
    assert http_client.calls == [
        (
            "post",
            "/api/v4/file-urls/batch",
            {
                "json": {
                    "files": [{"name": "guide.pdf"}],
                    "model_version": "vlm",
                },
                "headers": {"Authorization": "Bearer official-token"},
            },
        ),
        ("put", "https://oss.example/upload", {"data": b"%PDF-1.7"}),
        (
            "get",
            "/api/v4/extract-results/batch/batch-1",
            {"headers": {"Authorization": "Bearer official-token"}},
        ),
        ("get", "https://cdn.example/result.zip", {}),
    ]


@pytest.mark.asyncio
async def test_official_miner_failed_task_raises_document_conversion_failed():
    from app.infrastructure import mineru as mineru_infra

    http_client = FakeHttpClient(
        responses=[
            FakeResponse(
                json_data={
                    "code": 0,
                    "data": {
                        "batch_id": "batch-1",
                        "file_urls": ["https://oss.example/upload"],
                    },
                }
            ),
            FakeResponse(),
            FakeResponse(
                json_data={
                    "code": 0,
                    "data": {
                        "batch_id": "batch-1",
                        "extract_result": [
                            {
                                "file_name": "guide.pdf",
                                "state": "failed",
                                "err_msg": "parse failed",
                            }
                        ],
                    },
                }
            ),
        ],
    )
    miner = mineru_infra.OfficialMiner(
        http_client=http_client,
        api_key="official-token",
        model_version="vlm",
        poll_interval_seconds=0,
        poll_timeout_seconds=1,
    )

    with pytest.raises(DocumentConversionFailed):
        await miner.request_zip(filename="guide.pdf", content=b"%PDF-1.7")
