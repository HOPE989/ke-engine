from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import config
from app.services.document_api.app import create_app
from app.domains.document.shared.models import DocumentStatus


DOCUMENT_ENV = "\n".join(
    [
        "DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/app",
        "MAX_UPLOAD_SIZE_MB=5",
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


@pytest.fixture
async def configured_client(tmp_path, monkeypatch) -> AsyncIterator[tuple[AsyncClient, object]]:
    env_file = tmp_path / ".env"
    env_file.write_text(DOCUMENT_ENV, encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", env_file)
    for line in DOCUMENT_ENV.splitlines():
        monkeypatch.delenv(line.split("=", 1)[0], raising=False)
    config.get_settings.cache_clear()

    app = create_app()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, app

    config.get_settings.cache_clear()


class FakeRepository:
    def __init__(self, document):
        self.document = document
        self.doc_ids = []

    async def get_document(self, doc_id):
        self.doc_ids.append(doc_id)
        return self.document


@pytest.mark.asyncio
async def test_get_document_returns_current_metadata(configured_client):
    client, app = configured_client
    document = SimpleNamespace(
        doc_id=9_007_199_254_740_993,
        doc_title="guide.pdf",
        upload_user="alice",
        accessible_by="team-a",
        doc_url="https://files.example.com/documents/documents/9007199254740993/original/guide.pdf",
        converted_doc_url=None,
        status=DocumentStatus.UPLOADED.value,
    )
    repository = FakeRepository(document)
    app.state.document_deps = SimpleNamespace(repository=repository)

    response = await client.get("/api/v1/document/9007199254740993")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "doc_id": "9007199254740993",
        "doc_title": "guide.pdf",
        "upload_user": "alice",
        "accessible_by": "team-a",
        "doc_url": "https://files.example.com/documents/documents/9007199254740993/original/guide.pdf",
        "converted_doc_url": None,
        "status": "UPLOADED",
    }
    assert repository.doc_ids == [9_007_199_254_740_993]


@pytest.mark.asyncio
async def test_get_document_returns_404_when_missing(configured_client):
    client, app = configured_client
    app.state.document_deps = SimpleNamespace(repository=FakeRepository(None))

    response = await client.get("/api/v1/document/42")

    assert response.status_code == 404
    assert response.json() == {"code": 404, "message": "document not found", "data": None}
