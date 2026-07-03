from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from app.modules.document.errors import DocumentConversionFailed, DocumentStateRollbackFailed
from app.modules.document.file_types import DocumentFileType
from app.modules.document.models import DocumentStatus


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
        self.downloads = []

    async def download_bytes(self, *, object_key):
        self.downloads.append(object_key)
        return b"%PDF-1.7"

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


class FakeRepository:
    def __init__(self, *, rollback_failure=False):
        self.rollback_failure = rollback_failure
        self.document = SimpleNamespace(
            doc_id=42,
            doc_title="guide.pdf",
            upload_user="alice",
            accessible_by="team-a",
            file_type=DocumentFileType.PDF.value,
            doc_url="https://files.example.com/documents/documents/42/original/guide.pdf",
            converted_doc_url=None,
            status=DocumentStatus.UPLOADED.value,
        )
        self.events = []

    async def get_document(self, doc_id):
        self.events.append({"action": "get_document", "doc_id": doc_id})
        return self.document

    async def start_converting(self, *, doc_id):
        self.events.append({"action": "start_converting", "doc_id": doc_id})
        self.document.status = DocumentStatus.CONVERTING.value

    async def rollback_to_uploaded(self, *, doc_id):
        self.events.append({"action": "rollback_to_uploaded", "doc_id": doc_id})
        if self.rollback_failure:
            raise RuntimeError("rollback secret-key failed")
        self.document.status = DocumentStatus.UPLOADED.value

    async def mark_converted(self, *, doc_id, converted_doc_url, expected_status):
        self.events.append(
            {
                "action": "mark_converted",
                "doc_id": doc_id,
                "converted_doc_url": converted_doc_url,
                "expected_status": expected_status,
            }
        )
        self.document.status = DocumentStatus.CONVERTED.value
        self.document.converted_doc_url = converted_doc_url


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
async def test_pdf_conversion_failures_restore_uploaded(case):
    from app.modules.document.processing import convert_uploaded_document

    repository = FakeRepository()
    storage = FakeStorage(fail_on_object_key=case.get("fail_on_object_key"))
    mineru_client = FakeMinerUClient(
        zip_bytes=case.get("zip_bytes", b""),
        failure=case.get("mineru_failure"),
    )

    with pytest.raises(DocumentConversionFailed):
        await convert_uploaded_document(
            doc_id=42,
            document_repository=repository,
            storage=storage,
            mineru_client=mineru_client,
        )

    assert repository.document.status == DocumentStatus.UPLOADED.value
    assert repository.document.converted_doc_url is None
    assert repository.events[-1] == {"action": "rollback_to_uploaded", "doc_id": 42}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            {"zip_bytes": make_zip({"guide.md": "# Guide\n\n![](missing.png)\n"})},
            id="missing-image",
        ),
        pytest.param(
            {
                "zip_bytes": make_zip(
                    {"guide.md": "# Guide\n\n![](images/page-1.png)\n", "images/page-1.png": b"image"}
                ),
                "fail_on_object_key": "documents/42/assets/page-1.png",
            },
            id="asset-upload-failure",
        ),
    ],
)
async def test_pdf_conversion_image_failures_mark_converted(case):
    from app.modules.document.processing import convert_uploaded_document

    repository = FakeRepository()
    storage = FakeStorage(fail_on_object_key=case.get("fail_on_object_key"))
    mineru_client = FakeMinerUClient(zip_bytes=case["zip_bytes"])

    await convert_uploaded_document(
        doc_id=42,
        document_repository=repository,
        storage=storage,
        mineru_client=mineru_client,
    )

    assert repository.document.status == DocumentStatus.CONVERTED.value
    assert repository.document.converted_doc_url == (
        "https://files.example.com/documents/documents/42/converted/document.md"
    )
    assert repository.events[-1] == {
        "action": "mark_converted",
        "doc_id": 42,
        "converted_doc_url": "https://files.example.com/documents/documents/42/converted/document.md",
        "expected_status": DocumentStatus.CONVERTING,
    }
    assert {"action": "rollback_to_uploaded", "doc_id": 42} not in repository.events


@pytest.mark.asyncio
async def test_conversion_rollback_failure_preserves_converting_state():
    from app.modules.document.processing import convert_uploaded_document

    repository = FakeRepository(rollback_failure=True)

    with pytest.raises(DocumentStateRollbackFailed):
        await convert_uploaded_document(
            doc_id=42,
            document_repository=repository,
            storage=FakeStorage(),
            mineru_client=FakeMinerUClient(zip_bytes=b"not a zip"),
        )

    assert repository.document.status == DocumentStatus.CONVERTING.value
    assert repository.document.converted_doc_url is None
