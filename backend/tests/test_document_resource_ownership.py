import inspect
from types import SimpleNamespace

import pytest


def _document_settings():
    return SimpleNamespace(
        minio_endpoint="minio.example:9000",
        minio_access_key="access-key",
        minio_secret_key="secret-key",
        minio_secure=True,
        redis_url="redis://redis.example:6379/0",
        celery_broker_url="redis://redis.example:6379/0",
        celery_result_backend="redis://redis.example:6379/1",
        document_convert_lock_expire_seconds=120,
        snowflake_worker_id=7,
        mineru_provider="local",
        mineru_base_url="https://mineru.example.com",
        mineru_api_key=None,
        mineru_model_version="vlm",
        mineru_poll_interval_seconds=2,
        mineru_poll_timeout_seconds=300,
        mineru_timeout_seconds=30,
    )


def test_minio_client_is_created_by_cached_infrastructure_accessor(monkeypatch):
    from app.infrastructure import minio as minio_infra

    created_clients = []

    class FakeMinio:
        def __init__(self, endpoint, *, access_key, secret_key, secure):
            created_clients.append(
                {
                    "endpoint": endpoint,
                    "access_key": access_key,
                    "secret_key": secret_key,
                    "secure": secure,
                }
            )

    minio_infra.get_minio_client.cache_clear()
    monkeypatch.setattr(minio_infra, "get_settings", _document_settings)
    monkeypatch.setattr(minio_infra, "Minio", FakeMinio)

    try:
        first = minio_infra.get_minio_client()
        second = minio_infra.get_minio_client()
    finally:
        minio_infra.get_minio_client.cache_clear()

    assert first is second
    assert created_clients == [
        {
            "endpoint": "minio.example:9000",
            "access_key": "access-key",
            "secret_key": "secret-key",
            "secure": True,
        }
    ]


def test_magika_client_is_created_by_cached_infrastructure_accessor(monkeypatch):
    from app.infrastructure import magika as magika_infra

    created_clients = []

    class FakeMagika:
        def __init__(self):
            created_clients.append(self)

    magika_infra.get_magika_client.cache_clear()
    monkeypatch.setattr(magika_infra, "Magika", FakeMagika)

    try:
        first = magika_infra.get_magika_client()
        second = magika_infra.get_magika_client()
    finally:
        magika_infra.get_magika_client.cache_clear()

    assert first is second
    assert created_clients == [first]


def test_mineru_client_is_created_from_startup_settings(monkeypatch):
    from app.infrastructure import mineru as mineru_infra

    created_clients = []

    class FakeAsyncClient:
        def __init__(self, *, base_url, timeout):
            self.base_url = base_url
            self.timeout = timeout
            self.closed = False
            created_clients.append(self)

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(mineru_infra.httpx, "AsyncClient", FakeAsyncClient)

    miner = mineru_infra.create_mineru_client(_document_settings())

    assert isinstance(miner, mineru_infra.LocalMiner)
    assert created_clients == [miner.http_client]
    assert miner.http_client.base_url == "https://mineru.example.com"
    assert miner.http_client.timeout == 30


def test_upload_workflow_accepts_preowned_dependencies_without_resource_wrapper():
    from app.modules.document import workflow

    assert not hasattr(workflow, "DocumentUploadResources")
    upload_signature = inspect.signature(workflow.upload_document)
    assert list(upload_signature.parameters) == [
        "upload",
        "document_repository",
        "storage",
        "file_detector",
        "id_generator",
        "conversion_dispatcher",
    ]
    convert_signature = inspect.signature(workflow.convert_pdf_document)
    assert list(convert_signature.parameters) == [
        "doc_id",
        "upload",
        "storage",
        "mineru_client",
    ]

    source = inspect.getsource(workflow)
    for forbidden_constructor in ["Minio(", "Magika(", "httpx.AsyncClient("]:
        assert forbidden_constructor not in source
    assert "from app.modules.document.mineru import" not in source
    assert "request_mineru_zip" not in source
    assert "mineru_client.request_zip(" in source
    assert "conversion_dispatcher.dispatch(" in source


def test_document_repository_owns_short_lived_sessions():
    from app.modules.document import repository

    assert hasattr(repository, "DocumentRepository")
    assert not hasattr(repository, "create_init_document")
    assert not hasattr(repository, "mark_uploaded")
    assert not hasattr(repository, "start_converting")
    assert not hasattr(repository, "mark_converted")
    assert not hasattr(repository, "rollback_to_uploaded")

    init_signature = inspect.signature(repository.DocumentRepository.__init__)
    assert list(init_signature.parameters) == ["self", "session_factory"]

    source = inspect.getsource(repository.DocumentRepository)
    assert "async with self._session_factory() as session" in source


def test_document_runtime_groups_all_document_module_runtime_resources():
    from app.modules.document.runtime import DocumentRuntime

    signature = inspect.signature(DocumentRuntime)

    assert list(signature.parameters) == [
        "repository",
        "storage",
        "file_detector",
        "id_generator",
        "conversion_dispatcher",
    ]


def test_api_deps_avoid_redundant_document_app_state_getters():
    from app.api import deps

    assert not hasattr(deps, "DbSession")
    assert not hasattr(deps, "_require")
    assert not hasattr(deps, "get_document_repository")
    assert not hasattr(deps, "get_document_storage")
    assert not hasattr(deps, "get_document_file_detector")


def test_api_deps_own_document_runtime_initialization_layer():
    from app.api import deps

    source = inspect.getsource(deps)
    assert "def get_config()" in source
    assert "UploadLimits" not in source
    assert "def get_document_runtime(" in source
    assert "async def document_runtime" in source
    assert "document_upload_runtime" not in source
    assert "init_engine(settings.database_url)" in source
    assert "DocumentRepository(get_session_factory())" in source
    assert "DocumentRuntime(" in source
    assert "application.state.document_runtime" in source
    assert "DocumentObjectStorage(" in source
    assert "get_minio_client()" in source
    assert "ensure_minio_bucket(" in source
    assert "get_magika_client()" in source
    assert "SnowflakeIdGenerator(worker_id=settings.snowflake_worker_id)" in source
    assert "CeleryDocumentConversionDispatcher(" in source
    assert "push_async_callback(close_engine)" in source


@pytest.mark.asyncio
async def test_document_runtime_closes_engine_when_startup_fails(monkeypatch):
    from app.api import deps

    calls = []

    async def fake_init_engine(database_url):
        calls.append(("init_engine", database_url))

    async def fake_close_engine():
        calls.append(("close_engine", None))

    def fake_get_session_factory():
        return object()

    class FakeDocumentRepository:
        def __init__(self, session_factory):
            self.session_factory = session_factory

    def explode_minio_client():
        raise RuntimeError("minio unavailable")

    monkeypatch.setattr("app.db.session.init_engine", fake_init_engine)
    monkeypatch.setattr("app.db.session.close_engine", fake_close_engine)
    monkeypatch.setattr("app.db.session.get_session_factory", fake_get_session_factory)
    monkeypatch.setattr(
        "app.modules.document.repository.DocumentRepository",
        FakeDocumentRepository,
    )
    monkeypatch.setattr("app.infrastructure.minio.get_minio_client", explode_minio_client)

    app = SimpleNamespace(state=SimpleNamespace())
    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://user:pass@localhost:5432/app",
        minio_bucket="documents",
        minio_public_base_url="https://files.example.com",
        mineru_base_url="https://mineru.example.com",
        mineru_timeout_seconds=30,
        snowflake_worker_id=7,
    )

    with pytest.raises(RuntimeError, match="minio unavailable"):
        async with deps.document_runtime(app, settings):
            pass

    assert calls == [
        ("init_engine", "postgresql+asyncpg://user:pass@localhost:5432/app"),
        ("close_engine", None),
    ]
    assert not hasattr(app.state, "document_runtime")


@pytest.mark.asyncio
async def test_document_runtime_ensures_storage_bucket_before_serving(monkeypatch):
    from app.api import deps

    calls = []

    async def fake_init_engine(database_url):
        calls.append(("init_engine", database_url))

    async def fake_close_engine():
        calls.append(("close_engine", None))

    def fake_get_session_factory():
        return object()

    class FakeDocumentRepository:
        def __init__(self, session_factory):
            self.session_factory = session_factory

    class FakeMinerUClient:
        async def aclose(self):
            calls.append(("mineru_aclose", None))

    class FakeDocumentObjectStorage:
        def __init__(self, *, client, bucket, public_base_url):
            calls.append(("create_storage", bucket))
            self.client = client
            self.bucket = bucket
            self.public_base_url = public_base_url

    async def fake_ensure_minio_bucket(client, bucket):
        calls.append(("ensure_minio_bucket", bucket))

    class FakeSnowflakeIdGenerator:
        def __init__(self, *, worker_id):
            calls.append(("create_id_generator", worker_id))

    class FakeCeleryDocumentConversionDispatcher:
        def __init__(self):
            calls.append(("create_dispatcher", None))

    monkeypatch.setattr("app.db.session.init_engine", fake_init_engine)
    monkeypatch.setattr("app.db.session.close_engine", fake_close_engine)
    monkeypatch.setattr("app.db.session.get_session_factory", fake_get_session_factory)
    monkeypatch.setattr(
        "app.modules.document.repository.DocumentRepository",
        FakeDocumentRepository,
    )
    minio_client = object()
    monkeypatch.setattr("app.infrastructure.minio.get_minio_client", lambda: minio_client)
    monkeypatch.setattr("app.infrastructure.minio.ensure_minio_bucket", fake_ensure_minio_bucket)
    monkeypatch.setattr("app.infrastructure.magika.get_magika_client", lambda: object())
    monkeypatch.setattr(
        "app.modules.document.storage.DocumentObjectStorage",
        FakeDocumentObjectStorage,
    )
    monkeypatch.setattr(
        "app.infrastructure.snowflake.SnowflakeIdGenerator",
        FakeSnowflakeIdGenerator,
    )
    monkeypatch.setattr(
        "app.modules.document.tasks.CeleryDocumentConversionDispatcher",
        FakeCeleryDocumentConversionDispatcher,
    )

    app = SimpleNamespace(state=SimpleNamespace())
    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://user:pass@localhost:5432/app",
        minio_bucket="documents",
        minio_public_base_url="https://files.example.com",
        mineru_base_url="https://mineru.example.com",
        mineru_timeout_seconds=30,
        snowflake_worker_id=7,
    )

    async with deps.document_runtime(app, settings):
        assert calls == [
            ("init_engine", "postgresql+asyncpg://user:pass@localhost:5432/app"),
            ("ensure_minio_bucket", "documents"),
            ("create_storage", "documents"),
            ("create_id_generator", 7),
            ("create_dispatcher", None),
        ]
        assert app.state.document_runtime.storage.bucket == "documents"


def test_document_router_reads_config_through_api_deps():
    from app.modules.document import router

    source = inspect.getsource(router)
    assert "get_config" in source
    assert "Depends(get_config)" in source
    assert "max_upload_size_mb=settings.max_upload_size_mb" in source
    assert "UploadLimits" not in source
    assert "get_settings()" not in source


def test_document_router_reads_document_runtime_through_api_deps():
    from app.modules.document import router

    source = inspect.getsource(router)
    assert "Depends(get_document_runtime)" in source
    assert "request.app.state" not in source
    assert "document_runtime" in source
    assert "get_document_repository" not in source
    assert "get_document_storage" not in source
    assert "get_document_file_detector" not in source


def test_main_keeps_app_api_modules_layout_but_uses_lifespan_runtime():
    from app import main

    source = inspect.getsource(main)
    assert "from app.api.v1.router import api_router" in source
    assert "lifespan=" in source
    assert "from app.api.deps import document_runtime" in source
    assert "async with document_runtime(application, startup_settings)" in source
    assert "document_upload_runtime" not in source
    for implementation_detail in [
        "init_engine",
        "DocumentRepository",
        "DocumentObjectStorage",
        "get_minio_client",
        "get_magika_client",
    ]:
        assert implementation_detail not in source
