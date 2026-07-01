from collections.abc import AsyncIterator
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import config
from app.main import create_app
from app.modules.document import router as document_router
from app.modules.document import workflow
from app.modules.document.errors import DocumentStateConflict
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


def make_zip(entries: dict[str, bytes | str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class FakeMinerUClient:
    def __init__(self, *, zip_bytes=b"", failure=None):
        self.zip_bytes = zip_bytes
        self.failure = failure
        self.calls = []

    async def request_zip(self, *, filename, content):
        self.calls.append({"filename": filename, "content": content})
        if self.failure is not None:
            raise self.failure
        return self.zip_bytes


class FakeStorage:
    def __init__(self, *, fail_on_object_key=None):
        self.fail_on_object_key = fail_on_object_key
        self.uploads = []

    async def upload_bytes(self, *, object_key, content, content_type):
        if object_key == self.fail_on_object_key:
            raise RuntimeError("storage secret-key failed")
        self.uploads.append(
            {
                "object_key": object_key,
                "content": content,
                "content_type": content_type,
            }
        )
        return f"https://files.example.com/documents/{object_key}"


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


def force_pdf_detection(monkeypatch):
    def fake_detect_document_file_type(*, filename, content, upload_content_type, magika_client):
        return DocumentFileType.PDF

    monkeypatch.setattr(workflow, "detect_document_file_type", fake_detect_document_file_type)


def fake_repository(
    state,
    *,
    start_conflict=False,
    rollback_failure=False,
):
    async def create_init_document(*, doc_title, upload_user, accessible_by):
        state.update(
            {
                "doc_id": 42,
                "doc_title": doc_title,
                "upload_user": upload_user,
                "accessible_by": accessible_by,
                "status": DocumentStatus.INIT.value,
                "doc_url": None,
                "converted_doc_url": None,
            }
        )
        return SimpleNamespace(**state)

    async def mark_uploaded(*, doc_id, doc_url):
        state["status"] = DocumentStatus.UPLOADED.value
        state["doc_url"] = doc_url

    async def start_converting(*, doc_id):
        if start_conflict:
            raise DocumentStateConflict()
        state["status"] = DocumentStatus.CONVERTING.value

    async def rollback_to_uploaded(*, doc_id):
        if rollback_failure:
            raise RuntimeError("rollback secret-key failed")
        state["status"] = DocumentStatus.UPLOADED.value

    async def mark_converted(*, doc_id, converted_doc_url, expected_status):
        state["status"] = DocumentStatus.CONVERTED.value
        state["converted_doc_url"] = converted_doc_url

    return SimpleNamespace(
        create_init_document=create_init_document,
        mark_uploaded=mark_uploaded,
        start_converting=start_converting,
        rollback_to_uploaded=rollback_to_uploaded,
        mark_converted=mark_converted,
    )


def patch_router_dependencies(
    app,
    monkeypatch,
    storage,
    mineru_client,
    *,
    repository,
    file_detector=None,
):
    app.state.document_runtime = SimpleNamespace(
        repository=repository,
        storage=storage,
        file_detector=file_detector or object(),
        mineru_client=mineru_client,
    )


async def post_pdf(client):
    return await client.post(
        "/api/v1/document/upload",
        data={"upload_user": "alice", "accessible_by": "team-a"},
        files={"file": ("guide.pdf", b"%PDF-1.7", "application/pdf")},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            {"mineru_failure": RuntimeError("mineru secret-key failed")},
            id="mineru-request-failure",
        ),
        pytest.param({"zip_bytes": b"not a zip"}, id="corrupt-zip"),
        pytest.param({"zip_bytes": make_zip({"../evil.md": "# bad"})}, id="unsafe-zip"),
        pytest.param(
            {"zip_bytes": make_zip({"Guide.md": "# a", "guide.md": "# b"})},
            id="duplicate-normalized-zip-path",
        ),
        pytest.param({"zip_bytes": make_zip({"images/page-1.png": b"image"})}, id="no-markdown"),
        pytest.param(
            {"zip_bytes": make_zip({"guide.md": "# Guide\n\n![](missing.png)\n"})},
            id="markdown-rewrite-failure",
        ),
        pytest.param(
            {
                "zip_bytes": make_zip(
                    {"guide.md": "# Guide\n\n![](images/page-1.png)\n", "images/page-1.png": b"image"}
                ),
                "fail_on_object_key": "documents/42/assets/page-1.png",
            },
            id="converted-asset-upload-failure",
        ),
        pytest.param(
            {
                "zip_bytes": make_zip(
                    {"guide.md": "# Guide\n\n![](images/page-1.png)\n", "images/page-1.png": b"image"}
                ),
                "fail_on_object_key": "documents/42/converted/document.md",
            },
            id="converted-markdown-upload-failure",
        ),
    ],
)
async def test_pdf_conversion_failures_return_502_and_restore_uploaded(
    configured_client,
    monkeypatch,
    case,
):
    client, app = configured_client
    force_pdf_detection(monkeypatch)
    state = {}
    repository = fake_repository(state)
    storage = FakeStorage(fail_on_object_key=case.get("fail_on_object_key"))
    mineru_client = FakeMinerUClient(
        zip_bytes=case.get("zip_bytes", b""),
        failure=case.get("mineru_failure"),
    )
    patch_router_dependencies(
        app,
        monkeypatch,
        storage,
        mineru_client,
        repository=repository,
    )

    response = await post_pdf(client)

    assert response.status_code == 502
    assert response.json() == {"code": 502, "message": "document conversion failed", "data": None}
    assert "secret-key" not in response.text
    assert state["status"] == DocumentStatus.UPLOADED.value
    assert state["doc_url"] == "https://files.example.com/documents/documents/42/original/guide.pdf"
    assert state["converted_doc_url"] is None


@pytest.mark.asyncio
async def test_expected_state_conflict_returns_409_without_pdf_conversion(
    configured_client,
    monkeypatch,
):
    client, app = configured_client
    force_pdf_detection(monkeypatch)
    state = {}
    repository = fake_repository(state, start_conflict=True)
    storage = FakeStorage()
    mineru_client = FakeMinerUClient(
        zip_bytes=make_zip({"guide.md": "# Guide"}),
    )
    patch_router_dependencies(
        app,
        monkeypatch,
        storage,
        mineru_client,
        repository=repository,
    )

    response = await post_pdf(client)

    assert response.status_code == 409
    assert response.json() == {"code": 409, "message": "document state conflict", "data": None}
    assert mineru_client.calls == []
    assert state["status"] == DocumentStatus.UPLOADED.value
    assert state["converted_doc_url"] is None


@pytest.mark.asyncio
async def test_conversion_rollback_failure_returns_500(
    configured_client,
    monkeypatch,
):
    client, app = configured_client
    force_pdf_detection(monkeypatch)
    state = {}
    repository = fake_repository(state, rollback_failure=True)
    storage = FakeStorage()
    mineru_client = FakeMinerUClient(zip_bytes=b"not a zip")
    patch_router_dependencies(
        app,
        monkeypatch,
        storage,
        mineru_client,
        repository=repository,
    )

    response = await post_pdf(client)

    assert response.status_code == 500
    assert response.json() == {
        "code": 500,
        "message": "document state rollback failed",
        "data": None,
    }
    assert "secret-key" not in response.text
    assert state["status"] == DocumentStatus.CONVERTING.value
    assert state["doc_url"] == "https://files.example.com/documents/documents/42/original/guide.pdf"
    assert state["converted_doc_url"] is None
