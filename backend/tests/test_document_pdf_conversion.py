from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import config
from app.main import create_app
from app.modules.document import workflow
from app.modules.document.file_types import DocumentFileType
from app.modules.document.models import DocumentStatus
from app.modules.document.schemas import ValidatedDocumentUpload


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
    def __init__(self, zip_bytes: bytes):
        self.zip_bytes = zip_bytes
        self.calls = []

    async def request_zip(self, *, filename, content):
        self.calls.append({"filename": filename, "content": content})
        return self.zip_bytes


class FakeStorage:
    def __init__(self):
        self.uploads = []

    async def upload_bytes(self, *, object_key, content, content_type):
        self.uploads.append(
            {
                "object_key": object_key,
                "content": content,
                "content_type": content_type,
            }
        )
        return f"https://files.example.com/documents/{object_key}"


class FakeIdGenerator:
    def __init__(self, doc_id=9_007_199_254_740_993):
        self.doc_id = doc_id
        self.calls = 0

    def next_id(self):
        self.calls += 1
        return self.doc_id


class FakeConversionDispatcher:
    def __init__(self):
        self.doc_ids = []

    def dispatch(self, doc_id):
        self.doc_ids.append(doc_id)


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


def fake_repository(events):
    async def create_init_document(*, doc_id, doc_title, upload_user, accessible_by, file_type):
        events.append(
            {
                "action": "create_init",
                "doc_id": doc_id,
                "doc_title": doc_title,
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
        )

    async def mark_uploaded(*, doc_id, doc_url):
        events.append({"action": "mark_uploaded", "doc_id": doc_id, "doc_url": doc_url})

    return SimpleNamespace(
        create_init_document=create_init_document,
        mark_uploaded=mark_uploaded,
    )


def patch_router_dependencies(
    app,
    monkeypatch,
    storage,
    *,
    repository,
    id_generator,
    conversion_dispatcher,
    file_detector=None,
):
    app.state.document_runtime = SimpleNamespace(
        repository=repository,
        storage=storage,
        file_detector=file_detector or object(),
        id_generator=id_generator,
        conversion_dispatcher=conversion_dispatcher,
    )


@pytest.mark.asyncio
async def test_pdf_conversion_uploads_markdown_and_rewritten_images():
    zip_bytes = make_zip(
        {
            "guide.md": "# Guide\n\n![](images/page-1.png)\n",
            "images/page-1.png": b"image-bytes",
        }
    )
    mineru_client = FakeMinerUClient(zip_bytes)
    storage = FakeStorage()
    upload = ValidatedDocumentUpload(
        doc_title="guide.pdf",
        safe_filename="guide.pdf",
        upload_user="alice",
        accessible_by="team-a",
        content_type="application/pdf",
        content=b"%PDF-1.7",
        size_bytes=len(b"%PDF-1.7"),
    )

    converted_url = await workflow.convert_pdf_document(
        doc_id=42,
        upload=upload,
        storage=storage,
        mineru_client=mineru_client,
    )

    assert mineru_client.calls == [{"filename": "guide.pdf", "content": b"%PDF-1.7"}]
    assert storage.uploads == [
        {
            "object_key": "documents/42/assets/page-1.png",
            "content": b"image-bytes",
            "content_type": "image/png",
        },
        {
            "object_key": "documents/42/converted/document.md",
            "content": (
                "# Guide\n\n"
                "![图片描述](https://files.example.com/documents/documents/42/assets/page-1.png)\n"
            ).encode(),
            "content_type": "text/markdown",
        },
    ]
    assert converted_url == "https://files.example.com/documents/documents/42/converted/document.md"


def test_multiple_markdown_selection_prefers_pdf_conventions():
    from app.modules.document.markdown import select_markdown_path

    assert select_markdown_path([Path("other.md"), Path("guide.md")], "guide") == Path(
        "guide.md"
    )
    assert select_markdown_path(
        [Path("other.md"), Path("guide/result.md")],
        "guide",
    ) == Path("guide/result.md")
    assert select_markdown_path(
        [Path("zeta.md"), Path("alpha.md")],
        "guide",
    ) == Path("alpha.md")


@pytest.mark.asyncio
async def test_pdf_upload_api_persists_upload_and_dispatches_conversion(
    configured_client,
    monkeypatch,
):
    client, app = configured_client
    force_pdf_detection(monkeypatch)
    events = []
    repository = fake_repository(events)
    storage = FakeStorage()
    id_generator = FakeIdGenerator()
    dispatcher = FakeConversionDispatcher()
    patch_router_dependencies(
        app,
        monkeypatch,
        storage,
        repository=repository,
        id_generator=id_generator,
        conversion_dispatcher=dispatcher,
    )

    response = await client.post(
        "/api/v1/document/upload",
        data={"upload_user": "alice", "accessible_by": "team-a"},
        files={"file": ("guide.pdf", b"%PDF-1.7", "application/pdf")},
    )

    assert response.status_code == 202
    assert response.json()["data"] == {
        "doc_id": "9007199254740993",
        "doc_title": "guide.pdf",
        "upload_user": "alice",
        "accessible_by": "team-a",
        "doc_url": (
            "https://files.example.com/documents/"
            "documents/9007199254740993/original/guide.pdf"
        ),
        "converted_doc_url": None,
        "status": "UPLOADED",
    }
    assert events == [
        {
            "action": "create_init",
            "doc_id": 9_007_199_254_740_993,
            "doc_title": "guide.pdf",
            "file_type": DocumentFileType.PDF,
        },
        {
            "action": "mark_uploaded",
            "doc_id": 9_007_199_254_740_993,
            "doc_url": (
                "https://files.example.com/documents/"
                "documents/9007199254740993/original/guide.pdf"
            ),
        },
    ]
    assert id_generator.calls == 1
    assert dispatcher.doc_ids == [9_007_199_254_740_993]
