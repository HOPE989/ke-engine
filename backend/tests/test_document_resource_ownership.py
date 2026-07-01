import inspect
from types import SimpleNamespace

import pytest


def _document_settings():
    return SimpleNamespace(
        minio_endpoint="minio.example:9000",
        minio_access_key="access-key",
        minio_secret_key="secret-key",
        minio_secure=True,
        mineru_base_url="https://mineru.example.com",
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


@pytest.mark.asyncio
async def test_mineru_client_is_reused_from_app_state_and_closed(monkeypatch):
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

    app = SimpleNamespace(state=SimpleNamespace())
    first_request = SimpleNamespace(app=app)
    second_request = SimpleNamespace(app=app)
    monkeypatch.setattr(mineru_infra, "get_settings", _document_settings)
    monkeypatch.setattr(mineru_infra.httpx, "AsyncClient", FakeAsyncClient)

    first = await mineru_infra.get_mineru_client(first_request)
    second = await mineru_infra.get_mineru_client(second_request)
    await mineru_infra.close_mineru_client(app)

    assert first is second
    assert created_clients == [first]
    assert first.base_url == "https://mineru.example.com"
    assert first.timeout == 30
    assert first.closed is True
    assert not hasattr(app.state, mineru_infra.MINERU_CLIENT_STATE_KEY)


def test_upload_workflow_accepts_preowned_dependencies_without_resource_wrapper():
    from app.modules.document import workflow

    assert not hasattr(workflow, "DocumentUploadResources")
    upload_signature = inspect.signature(workflow.upload_document)
    assert list(upload_signature.parameters) == [
        "upload",
        "document_repository",
        "storage",
        "file_detector",
        "mineru_client",
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


def test_api_deps_expose_app_state_getters_without_endpoint_session_alias():
    from app.api import deps

    assert not hasattr(deps, "DbSession")
    assert hasattr(deps, "_require")

    repository = object()
    storage = object()
    file_detector = object()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                document_repository=repository,
                document_storage=storage,
                document_file_detector=file_detector,
            )
        )
    )

    assert deps.get_document_repository(request) is repository
    assert deps.get_document_storage(request) is storage
    assert deps.get_document_file_detector(request) is file_detector
    assert deps.get_document_repository.__name__ == "get_document_repository"


def test_api_deps_own_document_runtime_initialization_layer():
    from app.api import deps

    source = inspect.getsource(deps)
    assert "def get_config()" in source
    assert "async def document_upload_runtime" in source
    assert "init_engine(settings.database_url)" in source
    assert "DocumentRepository(get_session_factory())" in source
    assert "DocumentObjectStorage(" in source
    assert "get_minio_client()" in source
    assert "get_magika_client()" in source
    assert "close_mineru_client(application)" in source
    assert "close_engine()" in source


def test_document_router_reads_config_through_api_deps():
    from app.modules.document import router

    source = inspect.getsource(router)
    assert "get_config" in source
    assert "Depends(get_config)" in source
    assert "get_settings()" not in source


def test_main_keeps_app_api_modules_layout_but_uses_lifespan_runtime():
    from app import main

    source = inspect.getsource(main)
    assert "from app.api.v1.router import api_router" in source
    assert "lifespan=" in source
    assert "from app.api.deps import document_upload_runtime" in source
    assert "async with document_upload_runtime(application, startup_settings)" in source
    for implementation_detail in [
        "init_engine",
        "DocumentRepository",
        "DocumentObjectStorage",
        "get_minio_client",
        "get_magika_client",
    ]:
        assert implementation_detail not in source
