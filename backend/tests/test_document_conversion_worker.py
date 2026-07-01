from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from app.modules.document.errors import DocumentConversionFailed, DocumentStateConflict
from app.modules.document.file_types import DocumentFileType
from app.modules.document.models import DocumentStatus


def make_zip(entries: dict[str, bytes | str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class FakeRepository:
    def __init__(
        self,
        document,
        *,
        start_conflict=False,
        rollback_failure=False,
    ):
        self.document = document
        self.start_conflict = start_conflict
        self.rollback_failure = rollback_failure
        self.events = []

    async def get_document(self, doc_id):
        self.events.append({"action": "get_document", "doc_id": doc_id})
        return self.document

    async def start_converting(self, *, doc_id):
        self.events.append({"action": "start_converting", "doc_id": doc_id})
        if self.start_conflict:
            raise DocumentStateConflict()
        self.document.status = DocumentStatus.CONVERTING.value

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

    async def rollback_to_uploaded(self, *, doc_id):
        self.events.append({"action": "rollback_to_uploaded", "doc_id": doc_id})
        if self.rollback_failure:
            raise RuntimeError("rollback secret-key failed")
        self.document.status = DocumentStatus.UPLOADED.value


class FakeStorage:
    def __init__(self, *, downloads=None, fail_on_object_key=None):
        self.downloads = dict(downloads or {})
        self.fail_on_object_key = fail_on_object_key
        self.download_calls = []
        self.uploads = []

    async def download_bytes(self, *, object_key):
        self.download_calls.append(object_key)
        if object_key == self.fail_on_object_key:
            raise RuntimeError("download secret-key failed")
        return self.downloads[object_key]

    async def upload_bytes(self, *, object_key, content, content_type):
        if object_key == self.fail_on_object_key:
            raise RuntimeError("upload secret-key failed")
        self.uploads.append(
            {
                "object_key": object_key,
                "content": content,
                "content_type": content_type,
            }
        )
        return f"https://files.example.com/documents/{object_key}"


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


class FakeLock:
    def __init__(self, *, acquired=True):
        self.acquired = acquired
        self.acquire_calls = []
        self.released = False

    def acquire(self, *, blocking):
        self.acquire_calls.append({"blocking": blocking})
        return self.acquired

    def release(self):
        self.released = True


def _document(*, file_type, status=DocumentStatus.UPLOADED.value):
    return SimpleNamespace(
        doc_id=42,
        doc_title="guide.pdf" if file_type == DocumentFileType.PDF.value else "guide.md",
        upload_user="alice",
        accessible_by="team-a",
        file_type=file_type,
        doc_url=(
            "https://files.example.com/documents/"
            "documents/42/original/guide.pdf"
            if file_type == DocumentFileType.PDF.value
            else "https://files.example.com/documents/documents/42/original/guide.md"
        ),
        converted_doc_url=None,
        status=status,
    )


@pytest.mark.asyncio
async def test_worker_converts_plain_text_document_without_downloading_original():
    from app.modules.document.processing import convert_uploaded_document

    document = _document(file_type=DocumentFileType.PLAIN_TEXT.value)
    repository = FakeRepository(document)
    storage = FakeStorage()
    mineru_client = FakeMinerUClient()

    await convert_uploaded_document(
        doc_id=42,
        document_repository=repository,
        storage=storage,
        mineru_client=mineru_client,
    )

    assert repository.events == [
        {"action": "get_document", "doc_id": 42},
        {"action": "start_converting", "doc_id": 42},
        {
            "action": "mark_converted",
            "doc_id": 42,
            "converted_doc_url": (
                "https://files.example.com/documents/documents/42/original/guide.md"
            ),
            "expected_status": DocumentStatus.CONVERTING,
        },
    ]
    assert storage.download_calls == []
    assert mineru_client.calls == []
    assert document.status == DocumentStatus.CONVERTED.value


@pytest.mark.asyncio
async def test_worker_converts_pdf_from_original_object_and_uploads_markdown():
    from app.modules.document.processing import convert_uploaded_document

    document = _document(file_type=DocumentFileType.PDF.value)
    repository = FakeRepository(document)
    storage = FakeStorage(
        downloads={"documents/42/original/guide.pdf": b"%PDF-1.7"},
    )
    mineru_client = FakeMinerUClient(
        zip_bytes=make_zip(
            {
                "guide.md": "# Guide\n\n![](images/page-1.png)\n",
                "images/page-1.png": b"image-bytes",
            }
        )
    )

    await convert_uploaded_document(
        doc_id=42,
        document_repository=repository,
        storage=storage,
        mineru_client=mineru_client,
    )

    assert storage.download_calls == ["documents/42/original/guide.pdf"]
    assert mineru_client.calls == [{"filename": "guide.pdf", "content": b"%PDF-1.7"}]
    assert repository.events[-1] == {
        "action": "mark_converted",
        "doc_id": 42,
        "converted_doc_url": "https://files.example.com/documents/documents/42/converted/document.md",
        "expected_status": DocumentStatus.CONVERTING,
    }
    assert document.status == DocumentStatus.CONVERTED.value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "storage_failure_key, mineru_failure",
    [
        ("documents/42/original/guide.pdf", None),
        (None, RuntimeError("mineru secret-key failed")),
        ("documents/42/assets/page-1.png", None),
        ("documents/42/converted/document.md", None),
    ],
)
async def test_worker_rolls_back_to_uploaded_when_pdf_conversion_fails(
    storage_failure_key,
    mineru_failure,
):
    from app.modules.document.processing import convert_uploaded_document

    document = _document(file_type=DocumentFileType.PDF.value)
    repository = FakeRepository(document)
    storage = FakeStorage(
        downloads={"documents/42/original/guide.pdf": b"%PDF-1.7"},
        fail_on_object_key=storage_failure_key,
    )
    mineru_client = FakeMinerUClient(
        zip_bytes=make_zip(
            {
                "guide.md": "# Guide\n\n![](images/page-1.png)\n",
                "images/page-1.png": b"image-bytes",
            }
        ),
        failure=mineru_failure,
    )

    with pytest.raises(DocumentConversionFailed):
        await convert_uploaded_document(
            doc_id=42,
            document_repository=repository,
            storage=storage,
            mineru_client=mineru_client,
        )

    assert repository.events[-1] == {"action": "rollback_to_uploaded", "doc_id": 42}
    assert document.status == DocumentStatus.UPLOADED.value
    assert document.converted_doc_url is None


@pytest.mark.asyncio
async def test_worker_skips_conversion_when_state_transition_conflicts():
    from app.modules.document.processing import convert_uploaded_document

    document = _document(file_type=DocumentFileType.PDF.value)
    repository = FakeRepository(document, start_conflict=True)
    storage = FakeStorage(downloads={"documents/42/original/guide.pdf": b"%PDF-1.7"})
    mineru_client = FakeMinerUClient(zip_bytes=make_zip({"guide.md": "# Guide"}))

    await convert_uploaded_document(
        doc_id=42,
        document_repository=repository,
        storage=storage,
        mineru_client=mineru_client,
    )

    assert storage.download_calls == []
    assert mineru_client.calls == []
    assert repository.events == [
        {"action": "get_document", "doc_id": 42},
        {"action": "start_converting", "doc_id": 42},
    ]


@pytest.mark.asyncio
async def test_worker_lock_runs_conversion_once_and_releases_lock():
    from app.modules.document.processing import convert_document_with_lock

    document = _document(file_type=DocumentFileType.PLAIN_TEXT.value)
    repository = FakeRepository(document)
    storage = FakeStorage()
    mineru_client = FakeMinerUClient()
    lock = FakeLock(acquired=True)

    await convert_document_with_lock(
        doc_id=42,
        document_repository=repository,
        storage=storage,
        mineru_client=mineru_client,
        lock=lock,
    )

    assert lock.acquire_calls == [{"blocking": False}]
    assert lock.released is True
    assert [event["action"] for event in repository.events] == [
        "get_document",
        "start_converting",
        "mark_converted",
    ]


@pytest.mark.asyncio
async def test_worker_lock_skips_conversion_when_lock_is_busy():
    from app.modules.document.processing import convert_document_with_lock

    document = _document(file_type=DocumentFileType.PLAIN_TEXT.value)
    repository = FakeRepository(document)
    lock = FakeLock(acquired=False)

    await convert_document_with_lock(
        doc_id=42,
        document_repository=repository,
        storage=FakeStorage(),
        mineru_client=FakeMinerUClient(),
        lock=lock,
    )

    assert lock.acquire_calls == [{"blocking": False}]
    assert lock.released is False
    assert repository.events == []
