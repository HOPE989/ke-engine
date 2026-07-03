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


class FakeImageDescriber:
    def __init__(self, result="worker generated description", failure=None):
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
    image_describer = FakeImageDescriber("worker generated description")

    await convert_uploaded_document(
        doc_id=42,
        document_repository=repository,
        storage=storage,
        mineru_client=mineru_client,
        image_describer=image_describer,
    )

    assert storage.download_calls == ["documents/42/original/guide.pdf"]
    assert mineru_client.calls == [{"filename": "guide.pdf", "content": b"%PDF-1.7"}]
    assert repository.events[-1] == {
        "action": "mark_converted",
        "doc_id": 42,
        "converted_doc_url": "https://files.example.com/documents/documents/42/converted/document.md",
        "expected_status": DocumentStatus.CONVERTING,
    }
    assert storage.uploads[-1] == {
        "object_key": "documents/42/converted/document.md",
        "content": (
            "# Guide\n\n"
            "![worker generated description](https://files.example.com/documents/documents/42/assets/page-1.png)\n"
        ).encode(),
        "content_type": "text/markdown",
    }
    assert image_describer.calls == [
        {
            "filename": "page-1.png",
            "content": b"image-bytes",
            "content_type": "image/png",
        }
    ]
    assert document.status == DocumentStatus.CONVERTED.value


@pytest.mark.asyncio
async def test_locked_worker_injects_image_describer(monkeypatch):
    from app.db import session as session_module
    from app.modules.document import processing as processing_module
    from app.modules.document import repository as repository_module
    from app.modules.document.workers import conversion as conversion_worker

    calls = []

    async def fake_init_engine(database_url):
        calls.append({"action": "init_engine", "database_url": database_url})

    async def fake_close_engine():
        calls.append({"action": "close_engine"})

    def fake_get_session_factory():
        return "session-factory"

    class FakeDocumentRepository:
        def __init__(self, session_factory):
            self.session_factory = session_factory

    class FakeLazyStorage:
        def __init__(self, settings):
            self.settings = settings

    class FakeLazyMinerUClient:
        def __init__(self, settings):
            self.settings = settings

        async def aclose(self):
            calls.append({"action": "mineru_close"})

    class FakeLazyImageDescriber:
        def __init__(self, settings):
            self.settings = settings

    async def fake_convert_uploaded_document(**kwargs):
        calls.append({"action": "convert_uploaded_document", "kwargs": kwargs})

    monkeypatch.setattr(session_module, "init_engine", fake_init_engine)
    monkeypatch.setattr(session_module, "close_engine", fake_close_engine)
    monkeypatch.setattr(session_module, "get_session_factory", fake_get_session_factory)
    monkeypatch.setattr(repository_module, "DocumentRepository", FakeDocumentRepository)
    monkeypatch.setattr(processing_module, "convert_uploaded_document", fake_convert_uploaded_document)
    monkeypatch.setattr(conversion_worker, "_LazyDocumentStorage", FakeLazyStorage)
    monkeypatch.setattr(conversion_worker, "_LazyMinerUClient", FakeLazyMinerUClient)
    monkeypatch.setattr(conversion_worker, "_LazyImageDescriber", FakeLazyImageDescriber, raising=False)

    settings = SimpleNamespace(database_url="postgresql://db")

    await conversion_worker.run_locked_document_conversion(doc_id=42, settings=settings)

    convert_call = next(call for call in calls if call["action"] == "convert_uploaded_document")
    assert isinstance(convert_call["kwargs"]["image_describer"], FakeLazyImageDescriber)
    assert convert_call["kwargs"]["image_describer"].settings is settings


@pytest.mark.asyncio
async def test_image_describer_invokes_langchain_with_human_message():
    from langchain_core.messages import HumanMessage

    from app.modules.document.workers.conversion import _LazyImageDescriber

    class FakeModel:
        def __init__(self):
            self.messages = None

        async def ainvoke(self, messages):
            self.messages = messages
            return SimpleNamespace(content="描述结果")

    model = FakeModel()
    describer = _LazyImageDescriber(
        SimpleNamespace(
            openai_api_key="test-key",
            openai_base_url=None,
            openai_model=None,
        )
    )
    describer._model = model

    result = await describer.describe_image(
        filename="page-1.png",
        content=b"image-bytes",
        content_type="image/png",
    )

    assert result == "描述结果"
    assert len(model.messages) == 1
    message = model.messages[0]
    assert isinstance(message, HumanMessage)
    assert message.content == [
        {
            "type": "text",
            "text": "请用一句简洁中文描述图片 page-1.png 的主要内容。",
        },
        {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64,aW1hZ2UtYnl0ZXM=",
            },
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "storage_failure_key, mineru_failure",
    [
        ("documents/42/original/guide.pdf", None),
        (None, RuntimeError("mineru secret-key failed")),
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
async def test_worker_marks_converted_when_pdf_asset_upload_fails():
    from app.modules.document.processing import convert_uploaded_document

    document = _document(file_type=DocumentFileType.PDF.value)
    repository = FakeRepository(document)
    storage = FakeStorage(
        downloads={"documents/42/original/guide.pdf": b"%PDF-1.7"},
        fail_on_object_key="documents/42/assets/page-1.png",
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

    assert repository.events[-1] == {
        "action": "mark_converted",
        "doc_id": 42,
        "converted_doc_url": "https://files.example.com/documents/documents/42/converted/document.md",
        "expected_status": DocumentStatus.CONVERTING,
    }
    assert storage.uploads[-1] == {
        "object_key": "documents/42/converted/document.md",
        "content": "# Guide\n\n![图片解析错误](images/page-1.png)\n".encode(),
        "content_type": "text/markdown",
    }
    assert document.status == DocumentStatus.CONVERTED.value
    assert document.converted_doc_url == (
        "https://files.example.com/documents/documents/42/converted/document.md"
    )


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
