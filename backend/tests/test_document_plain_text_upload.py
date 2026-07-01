from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import config
from app.main import create_app
from app.modules.document import router as document_router
from app.modules.document import workflow
from app.modules.document.file_types import DocumentFileType
from app.modules.document.models import DocumentStatus


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


class FakeStorage:
    def __init__(self, *, upload_failure=None):
        self.upload_failure = upload_failure
        self.ensure_bucket_calls = 0
        self.uploads = []

    async def ensure_bucket(self):
        self.ensure_bucket_calls += 1

    async def upload_bytes(self, *, object_key, content, content_type):
        if self.upload_failure is not None:
            raise self.upload_failure
        self.uploads.append(
            {
                "object_key": object_key,
                "content": content,
                "content_type": content_type,
            }
        )
        return f"https://files.example.com/documents/{object_key}"


class ExplodingMinerUClient:
    def __getattr__(self, name):
        raise AssertionError("plain text upload must not call MinerU")


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


def _force_plain_text_detection(monkeypatch, detections):
    def fake_detect_document_file_type(*, filename, content, magika_client):
        detections.append(
            {
                "filename": filename,
                "content": content,
                "magika_client": magika_client,
            }
        )
        return DocumentFileType.PLAIN_TEXT

    monkeypatch.setattr(
        workflow,
        "detect_document_file_type",
        fake_detect_document_file_type,
        raising=False,
    )


def _fake_repository(events):
    async def create_init_document(*, doc_title, upload_user, accessible_by):
        events.append(
            {
                "action": "create_init",
                "doc_title": doc_title,
                "upload_user": upload_user,
                "accessible_by": accessible_by,
            }
        )
        return SimpleNamespace(
            doc_id=42,
            doc_title=doc_title,
            upload_user=upload_user,
            accessible_by=accessible_by,
            status=DocumentStatus.INIT.value,
            doc_url=None,
            converted_doc_url=None,
        )

    async def mark_uploaded(*, doc_id, doc_url):
        events.append({"action": "mark_uploaded", "doc_id": doc_id, "doc_url": doc_url})

    async def mark_converted(*, doc_id, converted_doc_url, expected_status):
        events.append(
            {
                "action": "mark_converted",
                "doc_id": doc_id,
                "converted_doc_url": converted_doc_url,
                "expected_status": expected_status,
            }
        )

    return SimpleNamespace(
        create_init_document=create_init_document,
        mark_uploaded=mark_uploaded,
        mark_converted=mark_converted,
    )


def _patch_router_dependencies(
    app,
    monkeypatch,
    storage,
    mineru_client,
    *,
    repository,
    file_detector=None,
):
    app.state.document_repository = repository
    app.state.document_storage = storage
    app.state.document_file_detector = file_detector or object()

    async def fake_get_mineru_client(request):
        return mineru_client

    monkeypatch.setattr(document_router, "get_mineru_client", fake_get_mineru_client)


@pytest.mark.asyncio
async def test_markdown_upload_completes_plain_text_conversion(
    configured_client,
    monkeypatch,
):
    client, app = configured_client
    storage = FakeStorage()
    detections = []
    events = []
    _force_plain_text_detection(monkeypatch, detections)
    repository = _fake_repository(events)
    _patch_router_dependencies(
        app,
        monkeypatch,
        storage,
        ExplodingMinerUClient(),
        repository=repository,
    )

    response = await client.post(
        "/api/v1/document/upload",
        data={"upload_user": "alice", "accessible_by": "team-a"},
        files={"file": ("guide.md", b"# Guide", "text/markdown")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"] == {
        "doc_id": 42,
        "doc_title": "guide.md",
        "upload_user": "alice",
        "accessible_by": "team-a",
        "doc_url": "https://files.example.com/documents/documents/42/original/guide.md",
        "converted_doc_url": "https://files.example.com/documents/documents/42/original/guide.md",
        "status": "CONVERTED",
    }
    assert detections[0]["filename"] == "guide.md"
    assert storage.ensure_bucket_calls == 1
    assert storage.uploads == [
        {
            "object_key": "documents/42/original/guide.md",
            "content": b"# Guide",
            "content_type": "application/octet-stream",
        }
    ]
    assert events == [
        {
            "action": "create_init",
            "doc_title": "guide.md",
            "upload_user": "alice",
            "accessible_by": "team-a",
        },
        {
            "action": "mark_uploaded",
            "doc_id": 42,
            "doc_url": "https://files.example.com/documents/documents/42/original/guide.md",
        },
        {
            "action": "mark_converted",
            "doc_id": 42,
            "converted_doc_url": "https://files.example.com/documents/documents/42/original/guide.md",
            "expected_status": DocumentStatus.UPLOADED,
        },
    ]


@pytest.mark.asyncio
async def test_original_upload_failure_keeps_init_and_skips_conversion(
    configured_client,
    monkeypatch,
):
    client, app = configured_client
    storage = FakeStorage(upload_failure=RuntimeError("minio secret-key failed"))
    detections = []
    events = []
    _force_plain_text_detection(monkeypatch, detections)
    repository = _fake_repository(events)
    _patch_router_dependencies(
        app,
        monkeypatch,
        storage,
        ExplodingMinerUClient(),
        repository=repository,
    )

    response = await client.post(
        "/api/v1/document/upload",
        data={"upload_user": "alice", "accessible_by": "team-a"},
        files={"file": ("guide.md", b"# Guide", "text/markdown")},
    )

    assert response.status_code == 502
    payload = response.json()
    assert payload == {"code": 502, "message": "document storage failed", "data": None}
    assert "secret-key" not in response.text
    assert storage.ensure_bucket_calls == 1
    assert events == [
        {
            "action": "create_init",
            "doc_title": "guide.md",
            "upload_user": "alice",
            "accessible_by": "team-a",
        }
    ]
