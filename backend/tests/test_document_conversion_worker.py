from io import BytesIO
import inspect
import importlib.util
from types import ModuleType, SimpleNamespace
import sys
from zipfile import ZipFile

import pytest

from app.modules.document.errors import DocumentConversionFailed, DocumentStateConflict
from app.modules.document.file_types import DocumentFileType
from app.modules.document.models import DocumentStatus


def install_worker_dependency_stubs_if_missing():
    if importlib.util.find_spec("confluent_kafka") is not None:
        pass
    else:
        confluent_kafka_module = ModuleType("confluent_kafka")
        aio_module = ModuleType("confluent_kafka.aio")
        aio_module.AIOConsumer = type("AIOConsumer", (), {})
        aio_module.AIOProducer = type("AIOProducer", (), {})
        confluent_kafka_module.aio = aio_module
        sys.modules.setdefault("confluent_kafka", confluent_kafka_module)
        sys.modules.setdefault("confluent_kafka.aio", aio_module)

    if importlib.util.find_spec("redis") is None:
        redis_module = ModuleType("redis")

        class Redis:
            @classmethod
            def from_url(cls, redis_url):
                return cls()

        redis_module.Redis = Redis
        sys.modules.setdefault("redis", redis_module)

    if importlib.util.find_spec("redis_lock") is None:
        redis_lock_module = ModuleType("redis_lock")
        redis_lock_module.Lock = type("Lock", (), {})
        sys.modules.setdefault("redis_lock", redis_lock_module)


install_worker_dependency_stubs_if_missing()


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


def make_converter_factory():
    from app.modules.document.converters import create_default_document_converter_factory

    return create_default_document_converter_factory()


@pytest.mark.asyncio
async def test_conversion_consumer_subscribes_to_topic_and_group(monkeypatch):
    from app.modules.document.workers import conversion as conversion_worker

    calls = []
    runtime = SimpleNamespace(settings=SimpleNamespace(kafka_bootstrap_servers="kafka.example:9092"))

    class FakeKafkaConsumer:
        async def subscribe(self, topics):
            calls.append(("subscribe", topics))

        async def poll(self, *, timeout):
            calls.append(("poll", timeout))
            raise RuntimeError("stop consumer")

        async def close(self):
            calls.append(("close", None))

    def fake_create_kafka_consumer(*, bootstrap_servers, group_id):
        calls.append(("create_consumer", bootstrap_servers, group_id))
        return FakeKafkaConsumer()

    monkeypatch.setattr(conversion_worker, "create_kafka_consumer", fake_create_kafka_consumer)

    with pytest.raises(RuntimeError, match="stop consumer"):
        await conversion_worker.run_document_conversion_consumer(runtime)

    assert calls[:3] == [
        ("create_consumer", "kafka.example:9092", "ke-engine-document-converter"),
        ("subscribe", ["document.convert.requested"]),
        ("poll", 1.0),
    ]


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
async def test_convert_document_content_delegates_to_injected_converter_factory():
    from app.modules.document import processing

    document = _document(file_type=DocumentFileType.PLAIN_TEXT.value)
    storage = object()
    mineru_client = object()
    image_describer = object()
    calls = []

    class FakeConverterFactory:
        async def convert_document(
            self,
            *,
            document,
            storage,
            mineru_client,
            image_describer=None,
        ):
            calls.append(
                {
                    "document": document,
                    "storage": storage,
                    "mineru_client": mineru_client,
                    "image_describer": image_describer,
                }
            )
            return "https://files.example.com/documents/documents/42/converted/factory.md"

    converted_url = await processing._convert_document_content(
        document=document,
        storage=storage,
        mineru_client=mineru_client,
        image_describer=image_describer,
        converter_factory=FakeConverterFactory(),
    )

    assert converted_url == "https://files.example.com/documents/documents/42/converted/factory.md"
    assert calls == [
        {
            "document": document,
            "storage": storage,
            "mineru_client": mineru_client,
            "image_describer": image_describer,
        }
    ]


def test_convert_document_content_has_no_hardcoded_pdf_conversion_details():
    from app.modules.document import processing

    source = inspect.getsource(processing._convert_document_content)

    assert "converter_factory.convert_document" in source
    assert "default_document_converter_factory" not in source
    assert "convert_pdf_document" not in source
    assert "DocumentFileType.PDF" not in source
    assert "original_object_key" not in source


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
        converter_factory=make_converter_factory(),
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
        converter_factory=make_converter_factory(),
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
async def test_locked_worker_uses_kafka_runtime_resources(monkeypatch):
    from app.modules.document import processing as processing_module
    from app.modules.document.workers import conversion as conversion_worker

    calls = []

    async def fake_convert_uploaded_document(**kwargs):
        calls.append({"action": "convert_uploaded_document", "kwargs": kwargs})

    monkeypatch.setattr(processing_module, "convert_uploaded_document", fake_convert_uploaded_document)

    repository = object()
    storage = object()
    mineru_client = object()
    image_describer = object()
    converter_factory = object()
    runtime = SimpleNamespace(
        conversion=SimpleNamespace(
            repository=repository,
            storage=storage,
            mineru_client=mineru_client,
            image_describer=image_describer,
            converter_factory=converter_factory,
        ),
    )

    await conversion_worker.run_locked_document_conversion(doc_id=42, runtime=runtime)

    convert_call = next(call for call in calls if call["action"] == "convert_uploaded_document")
    assert convert_call["kwargs"] == {
        "doc_id": 42,
        "document_repository": repository,
        "storage": storage,
        "mineru_client": mineru_client,
        "image_describer": image_describer,
        "converter_factory": converter_factory,
    }


@pytest.mark.asyncio
async def test_conversion_uses_runtime_redis_client_and_per_document_lock(monkeypatch):
    from app.modules.document.workers import conversion as conversion_worker

    calls = []
    redis_client = object()

    class FakeLock:
        def acquire(self, *, blocking):
            calls.append(("acquire", blocking))
            return True

        def release(self):
            calls.append(("release", None))

    def fake_document_conversion_lock(*, redis_client, doc_id, expire_seconds):
        calls.append(("lock", redis_client, doc_id, expire_seconds))
        return FakeLock()

    async def fake_run_locked_document_conversion(*, doc_id, runtime):
        calls.append(("run_locked", doc_id, runtime))

    monkeypatch.setattr(
        "app.infrastructure.redis_lock.document_conversion_lock",
        fake_document_conversion_lock,
    )
    monkeypatch.setattr(
        conversion_worker,
        "run_locked_document_conversion",
        fake_run_locked_document_conversion,
    )
    runtime = SimpleNamespace(
        conversion=SimpleNamespace(
            redis_client=redis_client,
            lock_expire_seconds=180,
        ),
    )

    await conversion_worker.run_document_conversion(doc_id=42, runtime=runtime)

    assert calls == [
        ("lock", redis_client, 42, 180),
        ("acquire", False),
        ("run_locked", 42, runtime),
        ("release", None),
    ]


@pytest.mark.asyncio
async def test_conversion_message_does_not_initialize_or_close_runtime_owned_resources(
    monkeypatch,
):
    from app.db import session as session_module
    from app.modules.document.workers import conversion as conversion_worker

    async def fail_db_lifecycle(*args, **kwargs):
        raise AssertionError("conversion hot path must not own DB engine lifecycle")

    class BusyLock:
        def acquire(self, *, blocking):
            return False

    monkeypatch.setattr(session_module, "init_engine", fail_db_lifecycle)
    monkeypatch.setattr(session_module, "close_engine", fail_db_lifecycle)
    monkeypatch.setattr(
        "app.infrastructure.redis_lock.document_conversion_lock",
        lambda **kwargs: BusyLock(),
    )
    runtime = SimpleNamespace(
        conversion=SimpleNamespace(
            redis_client=object(),
            lock_expire_seconds=180,
        ),
    )

    await conversion_worker.run_document_conversion(doc_id=42, runtime=runtime)


def test_conversion_hot_path_uses_runtime_repository_without_db_lifecycle():
    from app.modules.document.workers import conversion as conversion_worker

    source = inspect.getsource(conversion_worker.run_locked_document_conversion)

    assert "conversion_context.repository" in source
    assert "init_engine" not in source
    assert "close_engine" not in source
    assert "get_session_factory" not in source


def test_conversion_hot_path_uses_runtime_owned_external_resources():
    from app.modules.document.workers import conversion as conversion_worker

    source = inspect.getsource(conversion_worker.run_locked_document_conversion)

    assert "conversion_context.storage" in source
    assert "conversion_context.mineru_client" in source
    assert "conversion_context.image_describer" in source
    assert "conversion_context.converter_factory" in source
    assert "default_document_converter_factory" not in source
    assert "_LazyDocumentStorage" not in source
    assert "_LazyMinerUClient" not in source
    assert "_LazyImageDescriber" not in source


def test_conversion_worker_removes_legacy_lazy_runtime_resource_helpers():
    from app.modules.document.workers import conversion as conversion_worker

    source = inspect.getsource(conversion_worker)

    assert "_LazyDocumentStorage" not in source
    assert "_LazyMinerUClient" not in source
    assert "_LazyImageDescriber" not in source


@pytest.mark.asyncio
async def test_image_describer_invokes_langchain_with_human_message():
    from langchain_core.messages import HumanMessage

    from app.workers.kafka_worker import RuntimeImageDescriber

    class FakeModel:
        def __init__(self):
            self.messages = None

        async def ainvoke(self, messages):
            self.messages = messages
            return SimpleNamespace(content="描述结果")

    model = FakeModel()
    describer = RuntimeImageDescriber(model=model)

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
async def test_kafka_worker_runtime_initializes_converter_factory_at_startup(monkeypatch):
    from app.workers import kafka_worker

    converter_factory = object()
    calls = []

    async def fake_initialize_runtime_database(*, stack, settings):
        return "session-factory"

    async def fake_create_worker_document_storage(*, settings):
        return "storage"

    def fake_create_document_converter_factory():
        calls.append("converter_factory")
        return converter_factory

    monkeypatch.setattr(
        kafka_worker,
        "initialize_runtime_database",
        fake_initialize_runtime_database,
    )
    monkeypatch.setattr(kafka_worker, "_create_worker_repository", lambda session_factory: "repository")
    monkeypatch.setattr(
        kafka_worker,
        "_create_worker_redis_client",
        lambda *, stack, settings: "redis-client",
    )
    monkeypatch.setattr(
        kafka_worker,
        "_create_worker_document_storage",
        fake_create_worker_document_storage,
    )
    monkeypatch.setattr(
        kafka_worker,
        "_create_worker_mineru_client",
        lambda *, stack, settings: "mineru-client",
    )
    monkeypatch.setattr(
        kafka_worker,
        "_create_worker_image_describer",
        lambda *, stack, settings: "image-describer",
    )
    monkeypatch.setattr(
        kafka_worker,
        "_create_worker_embedding_model",
        lambda *, settings: "embedding-model",
    )
    monkeypatch.setattr(
        kafka_worker,
        "_create_worker_vector_store",
        lambda *, stack, settings, embedding_model: "vector-store",
    )
    monkeypatch.setattr(
        kafka_worker,
        "_create_document_converter_factory",
        fake_create_document_converter_factory,
        raising=False,
    )

    runtime = await kafka_worker.create_kafka_worker_runtime(
        stack=object(),
        settings=SimpleNamespace(document_convert_lock_expire_seconds=180),
    )

    assert calls == ["converter_factory"]
    assert runtime.conversion.converter_factory is converter_factory


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
            converter_factory=make_converter_factory(),
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
        converter_factory=make_converter_factory(),
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
        converter_factory=make_converter_factory(),
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
        converter_factory=make_converter_factory(),
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
        converter_factory=make_converter_factory(),
    )

    assert lock.acquire_calls == [{"blocking": False}]
    assert lock.released is False
    assert repository.events == []
