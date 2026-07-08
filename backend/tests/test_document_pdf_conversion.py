from collections.abc import AsyncIterator
from io import BytesIO
import logging
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import config
from app.services.document_api.app import create_app
from app.domains.document.services import conversion as workflow
from app.domains.document.services import upload as upload_workflow
from app.domains.document.shared.file_types import DocumentFileType
from app.domains.document.shared.models import DocumentStatus
from app.domains.document.shared.schemas import ValidatedDocumentUpload


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
    def __init__(self, *, fail_on_object_key=None):
        self.fail_on_object_key = fail_on_object_key
        self.uploads = []

    async def upload_bytes(self, *, object_key, content, content_type):
        if object_key == self.fail_on_object_key:
            raise RuntimeError("storage failed")
        self.uploads.append(
            {
                "object_key": object_key,
                "content": content,
                "content_type": content_type,
            }
        )
        return f"https://files.example.com/documents/{object_key}"


class FakeImageDescriber:
    def __init__(self, result="generated page description", failure=None):
        self.result = result
        self.failure = failure
        self.calls = []

    async def describe_image(self, *, filename, content, content_type):
        self.calls.append(
            {
                "filename": filename,
                "content": content,
                "content_type": content_type,
            }
        )
        if self.failure is not None:
            raise self.failure
        return self.result


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

    async def dispatch(self, doc_id):
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

    monkeypatch.setattr(upload_workflow, "detect_document_file_type", fake_detect_document_file_type)


def fake_repository(events):
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
async def test_pdf_conversion_uploads_markdown_and_rewritten_images():
    zip_bytes = make_zip(
        {
            "guide.md": "# Guide\n\n![](images/page-1.png)\n",
            "images/page-1.png": b"image-bytes",
        }
    )
    mineru_client = FakeMinerUClient(zip_bytes)
    storage = FakeStorage()
    image_describer = FakeImageDescriber("generated page description")
    upload = ValidatedDocumentUpload(
        doc_title="guide.pdf",
        safe_filename="guide.pdf",
        upload_user="alice",
        accessible_by="team-a",
        description="PDF guide",
        knowledge_base_type="DOCUMENT_SEARCH",
        content_type="application/pdf",
        content=b"%PDF-1.7",
        size_bytes=len(b"%PDF-1.7"),
    )

    converted_url = await workflow.convert_pdf_document(
        doc_id=42,
        upload=upload,
        storage=storage,
        mineru_client=mineru_client,
        image_describer=image_describer,
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
                "![generated page description](https://files.example.com/documents/documents/42/assets/page-1.png)\n"
            ).encode(),
            "content_type": "text/markdown",
        },
    ]
    assert image_describer.calls == [
        {
            "filename": "page-1.png",
            "content": b"image-bytes",
            "content_type": "image/png",
        }
    ]
    assert converted_url == "https://files.example.com/documents/documents/42/converted/document.md"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "image_describer",
    [
        pytest.param(
            FakeImageDescriber(failure=RuntimeError("provider failed")),
            id="generic-description-failure",
        ),
        pytest.param(FakeImageDescriber("   \n\t"), id="blank-description"),
    ],
)
async def test_pdf_conversion_marks_description_failures_without_losing_image_url(
    image_describer,
    caplog,
):
    zip_bytes = make_zip(
        {
            "guide.md": "# Guide\n\n![](images/page-1.png)\n",
            "images/page-1.png": b"image-bytes",
        }
    )
    storage = FakeStorage()
    upload = ValidatedDocumentUpload(
        doc_title="guide.pdf",
        safe_filename="guide.pdf",
        upload_user="alice",
        accessible_by="team-a",
        description="PDF guide",
        knowledge_base_type="DOCUMENT_SEARCH",
        content_type="application/pdf",
        content=b"%PDF-1.7",
        size_bytes=len(b"%PDF-1.7"),
    )

    caplog.set_level(logging.WARNING, logger="app.domains.document.services.conversion")

    converted_url = await workflow.convert_pdf_document(
        doc_id=42,
        upload=upload,
        storage=storage,
        mineru_client=FakeMinerUClient(zip_bytes),
        image_describer=image_describer,
    )

    assert storage.uploads[-1] == {
        "object_key": "documents/42/converted/document.md",
        "content": (
            "# Guide\n\n"
            "![图片解析错误](https://files.example.com/documents/documents/42/assets/page-1.png)\n"
        ).encode(),
        "content_type": "text/markdown",
    }
    matching_records = [
        record
        for record in caplog.records
        if record.message == "document image description failed"
    ]
    assert len(matching_records) == 1
    assert matching_records[0].doc_id == 42
    assert matching_records[0].image_target == "images/page-1.png"
    assert converted_url == "https://files.example.com/documents/documents/42/converted/document.md"


@pytest.mark.asyncio
async def test_pdf_conversion_marks_missing_image_without_failing_conversion(caplog):
    zip_bytes = make_zip({"guide.md": "# Guide\n\n![](images/missing.png)\n"})
    storage = FakeStorage()
    image_describer = FakeImageDescriber("should not be called")
    upload = ValidatedDocumentUpload(
        doc_title="guide.pdf",
        safe_filename="guide.pdf",
        upload_user="alice",
        accessible_by="team-a",
        description="PDF guide",
        knowledge_base_type="DOCUMENT_SEARCH",
        content_type="application/pdf",
        content=b"%PDF-1.7",
        size_bytes=len(b"%PDF-1.7"),
    )

    caplog.set_level(logging.WARNING, logger="app.domains.document.services.conversion")

    converted_url = await workflow.convert_pdf_document(
        doc_id=42,
        upload=upload,
        storage=storage,
        mineru_client=FakeMinerUClient(zip_bytes),
        image_describer=image_describer,
    )

    assert storage.uploads == [
        {
            "object_key": "documents/42/converted/document.md",
            "content": "# Guide\n\n![图片解析错误](images/missing.png)\n".encode(),
            "content_type": "text/markdown",
        }
    ]
    matching_records = [
        record for record in caplog.records if record.message == "document image rewrite failed"
    ]
    assert len(matching_records) == 1
    assert matching_records[0].doc_id == 42
    assert matching_records[0].image_target == "images/missing.png"
    assert image_describer.calls == []
    assert converted_url == "https://files.example.com/documents/documents/42/converted/document.md"


@pytest.mark.asyncio
async def test_pdf_conversion_marks_asset_upload_failure_without_failing_conversion(caplog):
    zip_bytes = make_zip(
        {
            "guide.md": "# Guide\n\n![](images/page-1.png)\n",
            "images/page-1.png": b"image-bytes",
        }
    )
    storage = FakeStorage(fail_on_object_key="documents/42/assets/page-1.png")
    image_describer = FakeImageDescriber("should not be called")
    upload = ValidatedDocumentUpload(
        doc_title="guide.pdf",
        safe_filename="guide.pdf",
        upload_user="alice",
        accessible_by="team-a",
        description="PDF guide",
        knowledge_base_type="DOCUMENT_SEARCH",
        content_type="application/pdf",
        content=b"%PDF-1.7",
        size_bytes=len(b"%PDF-1.7"),
    )

    caplog.set_level(logging.WARNING, logger="app.domains.document.services.conversion")

    converted_url = await workflow.convert_pdf_document(
        doc_id=42,
        upload=upload,
        storage=storage,
        mineru_client=FakeMinerUClient(zip_bytes),
        image_describer=image_describer,
    )

    assert storage.uploads == [
        {
            "object_key": "documents/42/converted/document.md",
            "content": "# Guide\n\n![图片解析错误](images/page-1.png)\n".encode(),
            "content_type": "text/markdown",
        }
    ]
    matching_records = [
        record for record in caplog.records if record.message == "document image upload failed"
    ]
    assert len(matching_records) == 1
    assert matching_records[0].doc_id == 42
    assert matching_records[0].image_target == "images/page-1.png"
    assert image_describer.calls == []
    assert converted_url == "https://files.example.com/documents/documents/42/converted/document.md"


def test_multiple_markdown_selection_prefers_pdf_conventions():
    from app.domains.document.components.markdown_assets import select_markdown_path

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
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "description": "  PDF guide  ",
            "knowledgeBaseType": "DOCUMENT_SEARCH",
        },
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
            "description": "PDF guide",
            "knowledge_base_type": "DOCUMENT_SEARCH",
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
