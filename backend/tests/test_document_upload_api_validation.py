from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.datastructures import UploadFile

from app.core import config
from app.main import create_app


DOCUMENT_ENV = "\n".join(
    [
        "DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/app",
        "MAX_UPLOAD_SIZE_MB=1",
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


def assert_error_response(response, status_code: int, message: str) -> None:
    payload = response.json()
    assert response.status_code == status_code
    assert payload["code"] == status_code
    assert payload["message"] == message
    assert payload["data"] is None
    assert "secret-key" not in response.text
    assert "Traceback" not in response.text


def patch_router_dependencies(app, document_router, monkeypatch):
    from types import SimpleNamespace

    app.state.settings = config.get_settings()
    runtime = SimpleNamespace(
        repository=object(),
        storage=object(),
        file_detector=object(),
        id_generator=object(),
        conversion_dispatcher=object(),
        redis_client=object(),
    )
    app.state.document_runtime = runtime


class FakeMagikaOutput:
    def __init__(self, *, ct_label: str = "unknown", mime_type: str = "application/octet-stream"):
        self.ct_label = ct_label
        self.mime_type = mime_type


class FakeMagikaResult:
    def __init__(self, *, ct_label: str = "unknown", mime_type: str = "application/octet-stream"):
        self.output = FakeMagikaOutput(ct_label=ct_label, mime_type=mime_type)


class RecordingUploadLock:
    def __init__(self, *, acquired=True, failure=None, release_failure=None):
        self.acquired = acquired
        self.failure = failure
        self.release_failure = release_failure
        self.acquire_calls = []
        self.released = False

    def acquire(self, *, blocking):
        self.acquire_calls.append({"blocking": blocking})
        if self.failure is not None:
            raise self.failure
        return self.acquired

    def release(self):
        self.released = True
        if self.release_failure is not None:
            raise self.release_failure


class RecordingFileDetector:
    def identify_bytes(self, content):
        return FakeMagikaResult()


class RecordingDataQueryRepository:
    def __init__(self, *, conflict=False):
        self.conflict = conflict
        self.events = []

    async def create_data_query_document_with_table_reservation(self, **kwargs):
        self.events.append({"action": "reserve", **kwargs})
        if self.conflict:
            from app.modules.document.errors import DataQueryTableNameConflict

            raise DataQueryTableNameConflict()
        return SimpleNamespace(
            doc_id=kwargs["doc_id"],
            doc_title=kwargs["doc_title"],
            upload_user=kwargs["upload_user"],
            accessible_by=kwargs["accessible_by"],
            description=kwargs["description"],
            knowledge_base_type=kwargs["knowledge_base_type"],
            file_type=kwargs["file_type"],
            status="INIT",
        )

    async def mark_uploaded(self, *, doc_id, doc_url):
        self.events.append({"action": "mark_uploaded", "doc_id": doc_id, "doc_url": doc_url})

    async def delete_data_query_reservation(self, *, document_id):
        self.events.append({"action": "cleanup_reservation", "document_id": document_id})


class RecordingStorage:
    def __init__(self, *, failure=None):
        self.failure = failure
        self.uploads = []

    async def upload_bytes(self, *, object_key, content, content_type):
        self.uploads.append(
            {
                "object_key": object_key,
                "content": content,
                "content_type": content_type,
            }
        )
        if self.failure is not None:
            raise self.failure
        return f"https://files.example.com/documents/{object_key}"


class RecordingIdGenerator:
    def __init__(self):
        self.next_values = [1001, 1002]

    def next_id(self):
        return self.next_values.pop(0)


class RecordingDispatcher:
    def __init__(self):
        self.calls = []

    async def dispatch(self, doc_id):
        self.calls.append(doc_id)


@pytest.fixture
async def validation_client(tmp_path, monkeypatch) -> AsyncIterator[tuple[AsyncClient, list]]:
    env_file = tmp_path / ".env"
    env_file.write_text(DOCUMENT_ENV, encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", env_file)
    for line in DOCUMENT_ENV.splitlines():
        monkeypatch.delenv(line.split("=", 1)[0], raising=False)
    config.get_settings.cache_clear()

    app = create_app()
    workflow_calls = []

    try:
        from app.modules.document import router as document_router

        async def fail_if_workflow_is_called(**kwargs):
            workflow_calls.append(kwargs)
            raise AssertionError("invalid requests must not reach document workflow")

        monkeypatch.setattr(document_router, "upload_document", fail_if_workflow_is_called)
        patch_router_dependencies(app, document_router, monkeypatch)
    except (ImportError, AttributeError):
        pass

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, workflow_calls

    config.get_settings.cache_clear()


@pytest.fixture
async def client_with_capturing_workflow(
    tmp_path,
    monkeypatch,
) -> AsyncIterator[tuple[AsyncClient, dict]]:
    env_file = tmp_path / ".env"
    env_file.write_text(DOCUMENT_ENV, encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", env_file)
    for line in DOCUMENT_ENV.splitlines():
        monkeypatch.delenv(line.split("=", 1)[0], raising=False)
    config.get_settings.cache_clear()

    app = create_app()
    captured = {}

    try:
        from app.modules.document import router as document_router
        from app.modules.document.schemas import DocumentMetadata

        async def capture_upload(**kwargs):
            upload = kwargs["upload"]
            captured["upload"] = upload
            return DocumentMetadata(
                doc_id="42",
                doc_title=upload.doc_title,
                upload_user=upload.upload_user,
                accessible_by=upload.accessible_by,
                doc_url=f"https://files.example.com/documents/42/original/{upload.safe_filename}",
                converted_doc_url=f"https://files.example.com/documents/42/original/{upload.safe_filename}",
                status="CONVERTED",
            )

        monkeypatch.setattr(document_router, "upload_document", capture_upload)
        monkeypatch.setattr(
            document_router,
            "data_query_upload_lock",
            lambda **kwargs: RecordingUploadLock(),
            raising=False,
        )
        patch_router_dependencies(app, document_router, monkeypatch)
    except (ImportError, AttributeError):
        pass

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, captured

    config.get_settings.cache_clear()


@pytest.fixture
async def client_with_data_query_runtime(
    tmp_path,
    monkeypatch,
) -> AsyncIterator[tuple[AsyncClient, SimpleNamespace]]:
    env_file = tmp_path / ".env"
    env_file.write_text(DOCUMENT_ENV, encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", env_file)
    for line in DOCUMENT_ENV.splitlines():
        monkeypatch.delenv(line.split("=", 1)[0], raising=False)
    config.get_settings.cache_clear()

    app = create_app()
    runtime = SimpleNamespace(
        repository=RecordingDataQueryRepository(),
        storage=RecordingStorage(),
        file_detector=RecordingFileDetector(),
        id_generator=RecordingIdGenerator(),
        conversion_dispatcher=RecordingDispatcher(),
        redis_client=object(),
    )
    app.state.settings = config.get_settings()
    app.state.document_runtime = runtime

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, runtime

    config.get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "files"),
    [
        (
            {
                "upload_user": "alice",
                "accessible_by": "team-a",
                "knowledgeBaseType": "DOCUMENT_SEARCH",
            },
            None,
        ),
        (
            {"accessible_by": "team-a", "knowledgeBaseType": "DOCUMENT_SEARCH"},
            {"file": ("guide.md", b"# hi", "text/markdown")},
        ),
        (
            {"upload_user": "alice", "knowledgeBaseType": "DOCUMENT_SEARCH"},
            {"file": ("guide.md", b"# hi", "text/markdown")},
        ),
        (
            {"upload_user": "alice", "accessible_by": "team-a"},
            {"file": ("guide.md", b"# hi", "text/markdown")},
        ),
    ],
)
async def test_missing_required_multipart_fields_return_422(
    validation_client,
    data,
    files,
):
    client, workflow_calls = validation_client

    response = await client.post("/api/v1/document/upload", data=data, files=files)

    assert_error_response(response, 422, "request validation failed")
    assert workflow_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "file_tuple", "status_code", "message"),
    [
        (
            {
                "upload_user": "   ",
                "accessible_by": "team-a",
                "knowledgeBaseType": "DOCUMENT_SEARCH",
            },
            ("guide.md", b"# hi", "text/markdown"),
            400,
            "invalid upload request",
        ),
        (
            {
                "upload_user": "alice",
                "accessible_by": "\t  ",
                "knowledgeBaseType": "DOCUMENT_SEARCH",
            },
            ("guide.md", b"# hi", "text/markdown"),
            400,
            "invalid upload request",
        ),
        (
            {
                "upload_user": "alice",
                "accessible_by": "team-a",
                "knowledgeBaseType": "DOCUMENT_SEARCH",
            },
            ("guide.md", b"", "text/markdown"),
            400,
            "invalid upload request",
        ),
        (
            {
                "upload_user": "alice",
                "accessible_by": "team-a",
                "knowledgeBaseType": "DOCUMENT_SEARCH",
            },
            ("   ", b"# hi", "text/markdown"),
            400,
            "invalid upload request",
        ),
        (
            {
                "upload_user": "alice",
                "accessible_by": "team-a",
                "knowledgeBaseType": "DOCUMENT_SEARCH",
            },
            ("large.md", b"x" * (1024 * 1024 + 1), "text/markdown"),
            413,
            "file too large",
        ),
        (
            {"upload_user": "alice", "accessible_by": "team-a", "knowledgeBaseType": "   "},
            ("guide.md", b"# hi", "text/markdown"),
            400,
            "invalid upload request",
        ),
        (
            {"upload_user": "alice", "accessible_by": "team-a", "knowledgeBaseType": "OTHER"},
            ("guide.md", b"# hi", "text/markdown"),
            400,
            "invalid upload request",
        ),
    ],
)
async def test_invalid_upload_requests_return_error_before_workflow(
    validation_client,
    data,
    file_tuple,
    status_code,
    message,
):
    client, workflow_calls = validation_client

    response = await client.post(
        "/api/v1/document/upload",
        data=data,
        files={"file": file_tuple},
    )

    assert_error_response(response, status_code, message)
    assert workflow_calls == []


@pytest.mark.asyncio
async def test_empty_upload_filename_returns_invalid_request_before_workflow(
    validation_client,
):
    client, workflow_calls = validation_client
    boundary = "document-upload-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="upload_user"\r\n\r\n'
        "alice\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="accessible_by"\r\n\r\n'
        "team-a\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="knowledgeBaseType"\r\n\r\n'
        "DOCUMENT_SEARCH\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename=""\r\n'
        "Content-Type: text/markdown\r\n\r\n"
        "# hi\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    response = await client.post(
        "/api/v1/document/upload",
        content=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )

    assert_error_response(response, 400, "invalid upload request")
    assert workflow_calls == []


@pytest.mark.asyncio
async def test_unreadable_upload_stream_returns_invalid_request_before_workflow(
    validation_client,
    monkeypatch,
):
    client, workflow_calls = validation_client

    async def unreadable(self, size=-1):
        raise OSError("cannot read C:\\secret\\source.pdf")

    monkeypatch.setattr(UploadFile, "read", unreadable)

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "knowledgeBaseType": "DOCUMENT_SEARCH",
        },
        files={"file": ("guide.md", b"# hi", "text/markdown")},
    )

    assert_error_response(response, 400, "invalid upload request")
    assert "C:\\secret" not in response.text
    assert workflow_calls == []


@pytest.mark.asyncio
async def test_upload_validation_stops_reading_when_size_limit_is_exceeded():
    from app.modules.document.schemas import (
        DocumentFileTooLarge,
        validate_document_upload,
    )

    class ChunkedUpload:
        filename = "large.md"
        content_type = "text/markdown"

        def __init__(self):
            self.chunks = [
                b"a" * (512 * 1024),
                b"b" * (512 * 1024),
                b"c",
                b"this chunk must not be read",
            ]
            self.read_sizes = []

        async def read(self, size=-1):
            self.read_sizes.append(size)
            return self.chunks.pop(0)

    upload = ChunkedUpload()

    with pytest.raises(DocumentFileTooLarge):
        await validate_document_upload(
            file=upload,
            upload_user="alice",
            accessible_by="team-a",
            description=None,
            knowledge_base_type="DOCUMENT_SEARCH",
            max_upload_size_mb=1,
        )

    assert upload.chunks == [b"this chunk must not be read"]
    assert upload.read_sizes
    assert all(size > 0 for size in upload.read_sizes)


@pytest.mark.asyncio
async def test_path_like_filename_is_normalized_before_workflow(
    client_with_capturing_workflow,
):
    client, captured = client_with_capturing_workflow

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "knowledgeBaseType": "DOCUMENT_SEARCH",
        },
        files={"file": ("..\\secret/../guide.md", b"# hi", "text/markdown")},
    )

    assert response.status_code == 202
    upload = captured["upload"]
    assert upload.doc_title == "guide.md"
    assert upload.safe_filename == "guide.md"
    assert upload.description == ""
    assert upload.knowledge_base_type == "DOCUMENT_SEARCH"
    assert upload.content_type == "text/markdown"
    assert ".." not in upload.safe_filename
    assert "\\" not in upload.safe_filename
    assert "/" not in upload.safe_filename
    assert "secret" not in response.json()["data"]["doc_url"]


@pytest.mark.asyncio
async def test_data_query_upload_validation_trims_description_and_defaults_override(
    client_with_capturing_workflow,
):
    client, captured = client_with_capturing_workflow

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "description": "  查询数据源说明  ",
            "knowledgeBaseType": "DATA_QUERY",
            "tableName": "sales_2026",
        },
        files={"file": ("sales.csv", b"name,amount\nalice,10", "text/csv")},
    )

    assert response.status_code == 202
    upload = captured["upload"]
    assert upload.doc_title == "sales.csv"
    assert upload.description == "查询数据源说明"
    assert upload.knowledge_base_type == "DATA_QUERY"
    assert upload.table_name == "sales_2026"
    assert upload.is_override is False


@pytest.mark.asyncio
async def test_data_query_upload_rejects_missing_table_name_before_workflow(validation_client):
    client, workflow_calls = validation_client

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "knowledgeBaseType": "DATA_QUERY",
        },
        files={"file": ("sales.csv", b"name,amount\nalice,10", "text/csv")},
    )

    assert_error_response(response, 400, "invalid upload request")
    assert workflow_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("table_name", ["Sales", "sales-2026", "sales 2026", "销售表"])
async def test_data_query_upload_rejects_invalid_table_name_before_workflow(
    validation_client,
    table_name,
):
    client, workflow_calls = validation_client

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "knowledgeBaseType": "DATA_QUERY",
            "tableName": table_name,
        },
        files={"file": ("sales.csv", b"name,amount\nalice,10", "text/csv")},
    )

    assert_error_response(response, 400, "invalid upload request")
    assert workflow_calls == []


@pytest.mark.asyncio
async def test_data_query_upload_rejects_table_name_that_exceeds_generated_identifier_limit(
    validation_client,
):
    client, workflow_calls = validation_client

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "knowledgeBaseType": "DATA_QUERY",
            "tableName": "a" * 48,
        },
        files={"file": ("sales.csv", b"name,amount\nalice,10", "text/csv")},
    )

    assert_error_response(response, 400, "invalid upload request")
    assert workflow_calls == []


@pytest.mark.asyncio
async def test_document_search_upload_does_not_require_table_name(
    client_with_capturing_workflow,
):
    client, captured = client_with_capturing_workflow

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "knowledgeBaseType": "DOCUMENT_SEARCH",
        },
        files={"file": ("guide.md", b"# hi", "text/markdown")},
    )

    assert response.status_code == 202
    upload = captured["upload"]
    assert upload.knowledge_base_type == "DOCUMENT_SEARCH"
    assert upload.table_name is None
    assert upload.is_override is False


@pytest.mark.asyncio
async def test_data_query_non_spreadsheet_upload_returns_415_before_persistence(
    client_with_data_query_runtime,
    monkeypatch,
):
    from app.modules.document import router as document_router

    lock = RecordingUploadLock()
    monkeypatch.setattr(
        document_router,
        "data_query_upload_lock",
        lambda **kwargs: lock,
        raising=False,
    )
    client, runtime = client_with_data_query_runtime

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "knowledgeBaseType": "DATA_QUERY",
            "tableName": "sales",
        },
        files={"file": ("guide.md", b"# hi", "text/markdown")},
    )

    assert_error_response(response, 415, "unsupported file type")
    assert runtime.repository.events == []
    assert runtime.storage.uploads == []
    assert runtime.conversion_dispatcher.calls == []
    assert lock.acquire_calls == []


@pytest.mark.asyncio
async def test_data_query_upload_lock_busy_returns_409_before_persistence(
    client_with_data_query_runtime,
    monkeypatch,
):
    from app.modules.document import router as document_router

    lock = RecordingUploadLock(acquired=False)
    monkeypatch.setattr(
        document_router,
        "data_query_upload_lock",
        lambda **kwargs: lock,
        raising=False,
    )
    client, runtime = client_with_data_query_runtime

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "knowledgeBaseType": "DATA_QUERY",
            "tableName": "sales",
        },
        files={"file": ("sales.csv", b"name,amount\nalice,10", "text/csv")},
    )

    assert_error_response(response, 409, "data query upload busy")
    assert runtime.repository.events == []
    assert runtime.storage.uploads == []
    assert runtime.conversion_dispatcher.calls == []
    assert lock.acquire_calls == [{"blocking": False}]
    assert lock.released is False


@pytest.mark.asyncio
async def test_data_query_upload_lock_failure_returns_503_before_persistence(
    client_with_data_query_runtime,
    monkeypatch,
):
    from app.modules.document import router as document_router

    lock = RecordingUploadLock(failure=RuntimeError("redis down"))
    monkeypatch.setattr(
        document_router,
        "data_query_upload_lock",
        lambda **kwargs: lock,
        raising=False,
    )
    client, runtime = client_with_data_query_runtime

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "knowledgeBaseType": "DATA_QUERY",
            "tableName": "sales",
        },
        files={"file": ("sales.csv", b"name,amount\nalice,10", "text/csv")},
    )

    assert_error_response(response, 503, "data query upload lock unavailable")
    assert runtime.repository.events == []
    assert runtime.storage.uploads == []
    assert runtime.conversion_dispatcher.calls == []
    assert lock.acquire_calls == [{"blocking": False}]
    assert lock.released is False


@pytest.mark.asyncio
async def test_duplicate_data_query_table_name_returns_409_before_storage(
    client_with_data_query_runtime,
    monkeypatch,
):
    from app.modules.document import router as document_router

    lock = RecordingUploadLock()
    monkeypatch.setattr(
        document_router,
        "data_query_upload_lock",
        lambda **kwargs: lock,
        raising=False,
    )
    client, runtime = client_with_data_query_runtime
    runtime.repository = RecordingDataQueryRepository(conflict=True)
    runtime.repository.conflict = True

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "knowledgeBaseType": "DATA_QUERY",
            "tableName": "sales",
        },
        files={"file": ("sales.csv", b"name,amount\nalice,10", "text/csv")},
    )

    assert_error_response(response, 409, "table name conflict")
    assert runtime.repository.events[0]["action"] == "reserve"
    assert runtime.repository.events[0]["is_override"] is False
    assert runtime.storage.uploads == []
    assert runtime.conversion_dispatcher.calls == []
    assert lock.released is True


@pytest.mark.asyncio
async def test_data_query_override_intent_reaches_reservation_workflow(
    client_with_data_query_runtime,
    monkeypatch,
):
    from app.modules.document import router as document_router

    lock = RecordingUploadLock()
    monkeypatch.setattr(
        document_router,
        "data_query_upload_lock",
        lambda **kwargs: lock,
        raising=False,
    )
    client, runtime = client_with_data_query_runtime

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "knowledgeBaseType": "DATA_QUERY",
            "tableName": "sales",
            "isOverride": "true",
        },
        files={"file": ("sales.csv", b"name,amount\nalice,10", "text/csv")},
    )

    assert response.status_code == 202
    reserve_event = runtime.repository.events[0]
    assert reserve_event["action"] == "reserve"
    assert reserve_event["namespace"] == "alice"
    assert reserve_event["table_name"] == "sales"
    assert reserve_event["is_override"] is True
    assert reserve_event["extension"] == {"tableName": "sales", "isOverride": True}
    assert runtime.repository.events[1]["action"] == "mark_uploaded"
    assert runtime.conversion_dispatcher.calls == [1001]
    assert lock.released is True


@pytest.mark.asyncio
async def test_data_query_original_storage_failure_deletes_new_reservation(
    client_with_data_query_runtime,
    monkeypatch,
):
    from app.modules.document import router as document_router

    lock = RecordingUploadLock()
    monkeypatch.setattr(
        document_router,
        "data_query_upload_lock",
        lambda **kwargs: lock,
        raising=False,
    )
    client, runtime = client_with_data_query_runtime
    runtime.storage = RecordingStorage(failure=RuntimeError("minio failed"))

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "knowledgeBaseType": "DATA_QUERY",
            "tableName": "sales",
        },
        files={"file": ("sales.csv", b"name,amount\nalice,10", "text/csv")},
    )

    assert_error_response(response, 502, "document storage failed")
    assert [event["action"] for event in runtime.repository.events] == [
        "reserve",
        "cleanup_reservation",
    ]
    assert runtime.repository.events[1]["document_id"] == 1001
    assert runtime.conversion_dispatcher.calls == []
    assert lock.released is True


@pytest.mark.asyncio
async def test_data_query_upload_release_failure_after_success_does_not_mask_accepted_upload(
    client_with_data_query_runtime,
    monkeypatch,
):
    from app.modules.document import router as document_router

    lock = RecordingUploadLock(release_failure=RuntimeError("redis release failed"))
    monkeypatch.setattr(
        document_router,
        "data_query_upload_lock",
        lambda **kwargs: lock,
        raising=False,
    )
    client, runtime = client_with_data_query_runtime

    response = await client.post(
        "/api/v1/document/upload",
        data={
            "upload_user": "alice",
            "accessible_by": "team-a",
            "knowledgeBaseType": "DATA_QUERY",
            "tableName": "sales",
        },
        files={"file": ("sales.csv", b"name,amount\nalice,10", "text/csv")},
    )

    assert response.status_code == 202
    assert [event["action"] for event in runtime.repository.events] == [
        "reserve",
        "mark_uploaded",
    ]
    assert runtime.conversion_dispatcher.calls == [1001]
    assert lock.acquire_calls == [{"blocking": False}]
    assert lock.released is True
