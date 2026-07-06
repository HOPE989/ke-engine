from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import config
from app.main import create_app
from app.modules.document.models import DocumentStatus
from app.modules.document.schemas import DocumentChunkResponse


DOCUMENT_ENV = "\n".join(
    [
        "DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/app",
        "MAX_UPLOAD_SIZE_MB=1",
        "MINIO_ENDPOINT=minio.example:9000",
        "MINIO_ACCESS_KEY=access-key",
        "MINIO_SECRET_KEY=secret-key",
        "MINIO_BUCKET=documents",
        "MINIO_PUBLIC_BASE_URL=https://files.example.com",
        "MINIO_SECURE=true",
        "MINERU_BASE_URL=https://mineru.example.com",
        "MINERU_TIMEOUT_SECONDS=30",
    ]
)


def assert_error_response(response, status_code: int, message: str) -> None:
    payload = response.json()
    assert response.status_code == status_code
    assert payload["code"] == status_code
    assert payload["message"] == message
    assert payload["data"] is None


@pytest.fixture
async def chunk_api_client(tmp_path, monkeypatch) -> AsyncIterator[tuple[AsyncClient, dict]]:
    env_file = tmp_path / ".env"
    env_file.write_text(DOCUMENT_ENV, encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", env_file)
    for line in DOCUMENT_ENV.splitlines():
        monkeypatch.delenv(line.split("=", 1)[0], raising=False)
    config.get_settings.cache_clear()

    app = create_app()
    calls = {"workflow": [], "exception": None}

    from app.modules.document import router as document_router

    async def fake_chunk_document(**kwargs):
        calls["workflow"].append(kwargs)
        if calls["exception"] is not None:
            raise calls["exception"]
        return DocumentChunkResponse(doc_id=str(kwargs["doc_id"]), status="CHUNKED", segment_count=2)

    monkeypatch.setattr(document_router, "chunk_document", fake_chunk_document, raising=False)
    monkeypatch.setattr(
        document_router,
        "document_chunking_lock",
        lambda **kwargs: "chunk-lock",
        raising=False,
    )
    app.state.settings = config.get_settings()
    runtime = SimpleNamespace(
        repository="repository",
        storage="storage",
        file_detector=object(),
        id_generator="id-generator",
        conversion_dispatcher=object(),
        embed_store_dispatcher=object(),
        redis_client="redis-client",
    )
    app.state.document_runtime = runtime

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, calls

    config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chunk_endpoint_returns_success_api_response(chunk_api_client):
    client, calls = chunk_api_client

    response = await client.post(
        "/api/v1/document/42/chunk",
        json={"chunk_size": 100, "overlap": 10},
    )

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "success",
        "data": {"doc_id": "42", "status": "CHUNKED", "segment_count": 2},
    }
    assert calls["workflow"][0]["doc_id"] == 42
    assert calls["workflow"][0]["chunk_size"] == 100
    assert calls["workflow"][0]["overlap"] == 10
    assert calls["workflow"][0]["lock"] == "chunk-lock"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"chunk_size": 100},
        {"overlap": 10},
        {"chunk_size": "100", "overlap": 10},
        {"chunk_size": 100, "overlap": "10"},
    ],
)
async def test_chunk_endpoint_rejects_missing_or_non_integer_fields(chunk_api_client, payload):
    client, calls = chunk_api_client

    response = await client.post("/api/v1/document/42/chunk", json=payload)

    assert_error_response(response, 422, "request validation failed")
    assert calls["workflow"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"chunk_size": 0, "overlap": 0},
        {"chunk_size": -1, "overlap": 0},
        {"chunk_size": 100, "overlap": -1},
        {"chunk_size": 100, "overlap": 100},
    ],
)
async def test_chunk_endpoint_rejects_invalid_chunk_relationship(chunk_api_client, payload):
    client, calls = chunk_api_client

    response = await client.post("/api/v1/document/42/chunk", json=payload)

    assert_error_response(response, 400, "invalid chunk request")
    assert calls["workflow"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception_name", "status_code", "message"),
    [
        ("DocumentNotFound", 404, "document not found"),
        ("DocumentStateConflict", 409, "document state conflict"),
        ("ChunkLockUnavailable", 503, "chunk lock unavailable"),
        ("ConvertedMarkdownUnavailable", 502, "converted markdown unavailable"),
        ("ConvertedMarkdownInvalid", 422, "converted markdown invalid"),
        ("ChunkSplittingFailed", 500, "chunk splitting failed"),
        ("ChunkPersistenceFailed", 500, "chunk persistence failed"),
    ],
)
async def test_chunk_endpoint_maps_workflow_errors(
    chunk_api_client,
    exception_name,
    status_code,
    message,
):
    from app.modules.document import errors

    client, calls = chunk_api_client
    calls["exception"] = getattr(errors, exception_name)()

    response = await client.post(
        "/api/v1/document/42/chunk",
        json={"chunk_size": 100, "overlap": 10},
    )

    assert_error_response(response, status_code, message)
    assert len(calls["workflow"]) == 1


@pytest.fixture
async def embed_store_api_client(tmp_path, monkeypatch) -> AsyncIterator[tuple[AsyncClient, dict]]:
    env_file = tmp_path / ".env"
    env_file.write_text(DOCUMENT_ENV, encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", env_file)
    for line in DOCUMENT_ENV.splitlines():
        monkeypatch.delenv(line.split("=", 1)[0], raising=False)
    config.get_settings.cache_clear()

    app = create_app()
    calls = {
        "document": SimpleNamespace(doc_id=42, status=DocumentStatus.CHUNKED.value),
        "dispatches": [],
        "dispatch_error": None,
    }

    class FakeRepository:
        async def get_document(self, doc_id):
            return calls["document"]

    class FakeEmbedStoreDispatcher:
        async def dispatch(self, doc_id):
            calls["dispatches"].append(doc_id)
            if calls["dispatch_error"] is not None:
                raise calls["dispatch_error"]

    app.state.settings = config.get_settings()
    runtime = SimpleNamespace(
        repository=FakeRepository(),
        storage="storage",
        file_detector=object(),
        id_generator="id-generator",
        conversion_dispatcher=object(),
        embed_store_dispatcher=FakeEmbedStoreDispatcher(),
        redis_client="redis-client",
    )
    app.state.document_runtime = runtime

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, calls

    config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_embed_store_endpoint_dispatches_for_chunked_document(embed_store_api_client):
    client, calls = embed_store_api_client

    response = await client.post("/api/v1/document/42/embed-store")

    assert response.status_code == 200
    assert response.json() == {"code": 0, "message": "success", "data": None}
    assert calls["dispatches"] == [42]


@pytest.mark.asyncio
async def test_embed_store_endpoint_reports_dispatch_failure(embed_store_api_client):
    client, calls = embed_store_api_client
    calls["dispatch_error"] = RuntimeError("kafka unavailable")

    response = await client.post("/api/v1/document/42/embed-store")

    assert_error_response(response, 503, "vector storage dispatch failed")
    assert calls["dispatches"] == [42]


@pytest.mark.asyncio
async def test_embed_store_endpoint_rejects_missing_document(embed_store_api_client):
    client, calls = embed_store_api_client
    calls["document"] = None

    response = await client.post("/api/v1/document/42/embed-store")

    assert_error_response(response, 404, "document not found")
    assert calls["dispatches"] == []


@pytest.mark.asyncio
async def test_embed_store_endpoint_rejects_non_chunked_document(embed_store_api_client):
    client, calls = embed_store_api_client
    calls["document"] = SimpleNamespace(doc_id=42, status=DocumentStatus.CONVERTED.value)

    response = await client.post("/api/v1/document/42/embed-store")

    assert_error_response(response, 409, "document state conflict")
    assert calls["dispatches"] == []


@pytest.mark.asyncio
async def test_embed_store_endpoint_is_idempotent_for_vector_stored_document(embed_store_api_client):
    client, calls = embed_store_api_client
    calls["document"] = SimpleNamespace(doc_id=42, status=DocumentStatus.VECTOR_STORED.value)

    response = await client.post("/api/v1/document/42/embed-store")

    assert response.status_code == 200
    assert response.json() == {"code": 0, "message": "success", "data": None}
    assert calls["dispatches"] == []
