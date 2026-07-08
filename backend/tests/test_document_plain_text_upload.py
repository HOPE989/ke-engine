from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import config
from app.services.document_api.app import create_app
from app.domains.document.services import upload as workflow
from app.domains.document.shared.file_types import DocumentFileType
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


class FakeStorage:
    def __init__(self, *, upload_failure=None):
        self.upload_failure = upload_failure
        self.uploads = []

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


class FakeIdGenerator:
    def __init__(self, doc_id=9_007_199_254_740_993):
        self.doc_id = doc_id
        self.calls = 0

    def next_id(self):
        self.calls += 1
        return self.doc_id


class FakeConversionDispatcher:
    def __init__(self, *, failure=None):
        self.failure = failure
        self.doc_ids = []

    async def dispatch(self, doc_id):
        self.doc_ids.append(doc_id)
        if self.failure is not None:
            raise self.failure


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
    def fake_detect_document_file_type(*, filename, content, upload_content_type, magika_client):
        detections.append(
            {
                "filename": filename,
                "content": content,
                "upload_content_type": upload_content_type,
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
    async def create_init_document(
        *,
        doc_id,
        doc_title,
        upload_user,
        accessible_by,
        description,
        knowledge_base_type,
        file_type,
    ):
        events.append(
            {
                "action": "create_init",
                "doc_id": doc_id,
                "doc_title": doc_title,
                "upload_user": upload_user,
                "accessible_by": accessible_by,
                "description": description,
                "knowledge_base_type": knowledge_base_type,
                "file_type": file_type,
            }
        )
        return SimpleNamespace(
            doc_id=doc_id,
            doc_title=doc_title,
            upload_user=upload_user,
            accessible_by=accessible_by,
            file_type=file_type,
            status=DocumentStatus.INIT.value,
            doc_url=None,
            converted_doc_url=None,
        )

    async def mark_uploaded(*, doc_id, doc_url):
        events.append({"action": "mark_uploaded", "doc_id": doc_id, "doc_url": doc_url})

    return SimpleNamespace(
        create_init_document=create_init_document,
        mark_uploaded=mark_uploaded,
    )


def _patch_router_dependencies(
    app,
    monkeypatch,
    storage,
    *,
    repository,
    id_generator,
    conversion_dispatcher,
    file_detector=None,
):
    app.state.settings = config.get_settings()
    runtime = SimpleNamespace(
        repository=repository,
        storage=storage,
        file_detector=file_detector or object(),
        id_generator=id_generator,
        conversion_dispatcher=conversion_dispatcher,
    )
    app.state.document_deps = runtime


@pytest.mark.asyncio
async def test_markdown_upload_returns_uploaded_and_dispatches_conversion(
    configured_client,
    monkeypatch,
):
    client, app = configured_client
    storage = FakeStorage()
    detections = []
    events = []
    id_generator = FakeIdGenerator()
    dispatcher = FakeConversionDispatcher()
    _force_plain_text_detection(monkeypatch, detections)
    repository = _fake_repository(events)
    _patch_router_dependencies(
        app,
        monkeypatch,
        storage,
        repository=repository,
        id_generator=id_generator,
        conversion_dispatcher=dispatcher,
    )

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "description": "  Markdown guide  ",
            "knowledgeBaseType": "DOCUMENT_SEARCH",
        },
        files={"file": ("guide.md", b"# Guide", "text/markdown")},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"] == {
        "doc_id": "9007199254740993",
        "doc_title": "guide.md",
        "upload_user": "alice",
        "accessible_by": "team-a",
        "doc_url": (
            "https://files.example.com/documents/"
            "documents/9007199254740993/original/guide.md"
        ),
        "converted_doc_url": None,
        "status": "UPLOADED",
    }
    assert detections[0]["filename"] == "guide.md"
    assert detections[0]["upload_content_type"] == "text/markdown"
    assert storage.uploads == [
        {
            "object_key": "documents/9007199254740993/original/guide.md",
            "content": b"# Guide",
            "content_type": "application/octet-stream",
        }
    ]
    assert events == [
        {
            "action": "create_init",
            "doc_id": 9_007_199_254_740_993,
            "doc_title": "guide.md",
            "upload_user": "alice",
            "accessible_by": "team-a",
            "description": "Markdown guide",
            "knowledge_base_type": "DOCUMENT_SEARCH",
            "file_type": DocumentFileType.PLAIN_TEXT,
        },
        {
            "action": "mark_uploaded",
            "doc_id": 9_007_199_254_740_993,
            "doc_url": (
                "https://files.example.com/documents/"
                "documents/9007199254740993/original/guide.md"
            ),
        },
    ]
    assert id_generator.calls == 1
    assert dispatcher.doc_ids == [9_007_199_254_740_993]


@pytest.mark.asyncio
async def test_conversion_dispatch_failure_still_returns_uploaded(
    configured_client,
    monkeypatch,
):
    client, app = configured_client
    storage = FakeStorage()
    detections = []
    events = []
    id_generator = FakeIdGenerator(doc_id=43)
    dispatcher = FakeConversionDispatcher(failure=RuntimeError("redis secret-key failed"))
    _force_plain_text_detection(monkeypatch, detections)
    repository = _fake_repository(events)
    _patch_router_dependencies(
        app,
        monkeypatch,
        storage,
        repository=repository,
        id_generator=id_generator,
        conversion_dispatcher=dispatcher,
    )

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "knowledgeBaseType": "DOCUMENT_SEARCH",
        },
        files={"file": ("guide.md", b"# Guide", "text/markdown")},
    )

    assert response.status_code == 202
    assert "secret-key" not in response.text
    assert response.json()["data"]["status"] == DocumentStatus.UPLOADED.value
    assert response.json()["data"]["converted_doc_url"] is None
    assert dispatcher.doc_ids == [43]
    assert [event["action"] for event in events] == ["create_init", "mark_uploaded"]


@pytest.mark.asyncio
async def test_upload_workflow_runs_file_detection_in_threadpool(monkeypatch):
    detections = []
    threadpool_calls = []

    def fake_detect_document_file_type(*, filename, content, upload_content_type, magika_client):
        detections.append(
            {
                "filename": filename,
                "content": content,
                "upload_content_type": upload_content_type,
                "magika_client": magika_client,
            }
        )
        return DocumentFileType.PLAIN_TEXT

    async def fake_run_in_threadpool(func, *args, **kwargs):
        threadpool_calls.append({"func": func, "args": args, "kwargs": kwargs})
        return func(*args, **kwargs)

    monkeypatch.setattr(workflow, "detect_document_file_type", fake_detect_document_file_type)
    monkeypatch.setattr(workflow, "run_in_threadpool", fake_run_in_threadpool, raising=False)

    storage = FakeStorage()
    events = []
    repository = _fake_repository(events)
    id_generator = FakeIdGenerator(doc_id=45)
    dispatcher = FakeConversionDispatcher()

    await workflow.upload_document(
        upload=SimpleNamespace(
            doc_title="guide.md",
            safe_filename="guide.md",
            upload_user="alice",
            accessible_by="team-a",
            description="Markdown guide",
            knowledge_base_type="DOCUMENT_SEARCH",
            content_type="text/markdown",
            content=b"# Guide",
            size_bytes=7,
        ),
        document_repository=repository,
        storage=storage,
        file_detector=object(),
        id_generator=id_generator,
        conversion_dispatcher=dispatcher,
    )

    assert len(threadpool_calls) == 1
    assert threadpool_calls[0]["func"] is fake_detect_document_file_type
    assert detections[0]["filename"] == "guide.md"


@pytest.mark.asyncio
async def test_original_upload_failure_keeps_init_and_skips_conversion(
    configured_client,
    monkeypatch,
):
    client, app = configured_client
    storage = FakeStorage(upload_failure=RuntimeError("minio secret-key failed"))
    detections = []
    events = []
    id_generator = FakeIdGenerator(doc_id=44)
    dispatcher = FakeConversionDispatcher()
    _force_plain_text_detection(monkeypatch, detections)
    repository = _fake_repository(events)
    _patch_router_dependencies(
        app,
        monkeypatch,
        storage,
        repository=repository,
        id_generator=id_generator,
        conversion_dispatcher=dispatcher,
    )

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "knowledgeBaseType": "DOCUMENT_SEARCH",
        },
        files={"file": ("guide.md", b"# Guide", "text/markdown")},
    )

    assert response.status_code == 502
    payload = response.json()
    assert payload == {"code": 502, "message": "document storage failed", "data": None}
    assert "secret-key" not in response.text
    assert events == [
        {
            "action": "create_init",
            "doc_id": 44,
            "doc_title": "guide.md",
            "upload_user": "alice",
            "accessible_by": "team-a",
            "description": "",
            "knowledge_base_type": "DOCUMENT_SEARCH",
            "file_type": DocumentFileType.PLAIN_TEXT,
        }
    ]
    assert dispatcher.doc_ids == []
