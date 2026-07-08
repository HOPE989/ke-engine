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
        kafka_bootstrap_servers="kafka.example:9092",
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
    from app.domains.document.services import upload as workflow
    from app.domains.document.services import conversion as conversion_workflow

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
    convert_signature = inspect.signature(conversion_workflow.convert_pdf_document)
    assert list(convert_signature.parameters) == [
        "doc_id",
        "upload",
        "storage",
        "mineru_client",
        "image_describer",
    ]

    source = inspect.getsource(workflow)
    conversion_source = inspect.getsource(conversion_workflow)
    for forbidden_constructor in ["Minio(", "Magika(", "httpx.AsyncClient("]:
        assert forbidden_constructor not in source
        assert forbidden_constructor not in conversion_source
    assert "from app.modules.document.mineru import" not in source
    assert "from app.modules.document.mineru import" not in conversion_source
    assert "request_mineru_zip" not in source
    assert "request_mineru_zip" not in conversion_source
    assert "mineru_client.request_zip(" in conversion_source
    assert "await conversion_dispatcher.dispatch(" in source


def test_document_repository_owns_short_lived_sessions():
    from app.domains.document.repositories import document_repository as repository

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


def test_api_deps_define_document_module_dependencies_without_api_runtime():
    from app.services.document_api import deps

    assert not hasattr(deps, "ApiRuntime")
    signature = inspect.signature(deps.DocumentApiDeps)

    assert list(signature.parameters) == [
        "repository",
        "storage",
        "file_detector",
        "id_generator",
        "conversion_dispatcher",
        "embed_store_dispatcher",
        "splitter_factory",
        "redis_client",
    ]


def test_runtime_state_is_module_scoped_inside_api_process():
    from app.services.document_api import deps
    from app.entrypoints import celery_worker, document_worker as kafka_worker

    assert hasattr(deps, "DocumentApiDeps")
    assert not hasattr(deps, "ApiRuntime")
    assert hasattr(kafka_worker, "KafkaWorkerRuntime")
    assert hasattr(celery_worker, "CeleryWorkerRuntime")
    assert hasattr(kafka_worker, "DocumentConversionContext")
    assert hasattr(kafka_worker, "DocumentVectorStorageContext")
    assert hasattr(celery_worker, "DocumentCompensationContext")
    for forbidden_name in [
        "DocumentConversionRuntime",
        "DocumentVectorStorageRuntime",
        "DocumentCompensationRuntime",
        "VectorStorageRuntime",
        "CompensationRuntime",
    ]:
        assert not hasattr(deps, forbidden_name)
        assert not hasattr(kafka_worker, forbidden_name)
        assert not hasattr(celery_worker, forbidden_name)


def test_worker_runtime_contexts_are_typed_stage_views_not_lifecycle_owners():
    from app.entrypoints import celery_worker, document_worker as kafka_worker

    assert set(kafka_worker.KafkaWorkerRuntime.__dataclass_fields__) == {
        "settings",
        "session_factory",
        "conversion",
        "vector_storage",
    }
    assert set(celery_worker.CeleryWorkerRuntime.__dataclass_fields__) == {
        "settings",
        "session_factory",
        "compensation",
    }
    assert set(kafka_worker.DocumentConversionContext.__dataclass_fields__) == {
        "repository",
        "redis_client",
            "storage",
            "mineru_client",
            "image_describer",
            "converter_factory",
            "lock_expire_seconds",
        }
    assert set(kafka_worker.DocumentVectorStorageContext.__dataclass_fields__) == {
        "repository",
        "redis_client",
        "embedding_model",
        "vector_store",
        "lock_expire_seconds",
    }
    assert set(celery_worker.DocumentCompensationContext.__dataclass_fields__) == {
        "repository",
        "storage",
        "mineru_client",
        "image_describer",
        "vector_storage",
    }


@pytest.mark.asyncio
async def test_api_resource_cleanup_stack_runs_explicit_callbacks_in_reverse_order():
    from app.services.document_api.deps import ResourceCleanupStack

    calls = []

    def close_resource():
        calls.append("close")

    async def aclose_resource():
        calls.append("aclose")

    def dispose_resource():
        calls.append("dispose")

    async with ResourceCleanupStack() as stack:
        stack.push_cleanup(close_resource)
        stack.push_cleanup(aclose_resource)
        stack.push_cleanup(dispose_resource)
        calls.append("inside")

    assert calls == ["inside", "dispose", "aclose", "close"]


@pytest.mark.asyncio
async def test_database_deps_helper_initializes_session_factory_and_registers_cleanup(
    monkeypatch,
):
    from app.infrastructure.db import session as session_module
    from app.services.document_api import deps

    calls = []

    async def fake_init_engine(database_url):
        calls.append(("init_engine", database_url))

    async def fake_close_engine():
        calls.append(("close_engine", None))

    def fake_get_session_factory():
        calls.append(("get_session_factory", None))
        return "session-factory"

    monkeypatch.setattr(session_module, "init_engine", fake_init_engine)
    monkeypatch.setattr(session_module, "close_engine", fake_close_engine)
    monkeypatch.setattr(session_module, "get_session_factory", fake_get_session_factory)

    async with deps.ResourceCleanupStack() as stack:
        session_factory = await deps.initialize_database_deps(
            stack=stack,
            settings=SimpleNamespace(database_url="postgresql+asyncpg://db/app"),
        )
        assert session_factory == "session-factory"
        assert calls == [
            ("init_engine", "postgresql+asyncpg://db/app"),
            ("get_session_factory", None),
        ]

    assert calls == [
        ("init_engine", "postgresql+asyncpg://db/app"),
        ("get_session_factory", None),
        ("close_engine", None),
    ]


def test_worker_document_execution_paths_do_not_own_db_engine_lifecycle():
    from app.domains.document.tasks import vector_storage_compensation
    from app.domains.document.workers import conversion_consumer as conversion, vectorization_consumer as vector_storage

    hot_path_sources = [
        inspect.getsource(conversion.run_locked_document_conversion),
        inspect.getsource(vector_storage.run_document_vector_storage_with_runtime),
        inspect.getsource(vector_storage_compensation._scan_stale_chunked_document_ids),
    ]

    for source in hot_path_sources:
        assert "init_engine" not in source
        assert "close_engine" not in source


@pytest.mark.asyncio
async def test_kafka_worker_runtime_groups_startup_document_resources(monkeypatch):
    from app.infrastructure.db import session as session_module
    from app.entrypoints import document_worker as kafka_worker

    calls = []

    async def fake_init_engine(database_url):
        calls.append(("init_engine", database_url))

    async def fake_close_engine():
        calls.append(("close_engine", None))

    def fake_get_session_factory():
        return "session-factory"

    class FakeRepository:
        def __init__(self, session_factory):
            self.session_factory = session_factory

    class FakeRedis:
        def close(self):
            calls.append(("redis_close", None))

    class FakeStorage:
        def __init__(self, *, client, bucket, public_base_url):
            self.client = client
            self.bucket = bucket
            self.public_base_url = public_base_url

    class FakeAdapter:
        def __init__(self, *, store, client, index_name):
            self.store = store
            self.client = client
            self.index_name = index_name

    async def fake_ensure_minio_bucket(client, bucket):
        calls.append(("ensure_minio_bucket", bucket))

    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://db/app",
        redis_url="redis://redis.example:6379/0",
        minio_bucket="documents",
        minio_public_base_url="https://files.example.com",
        kafka_bootstrap_servers="kafka.example:9092",
        elasticsearch_index="doc-vectors",
        document_convert_lock_expire_seconds=120,
    )
    minio_client = object()
    mineru_client = object()
    image_describer = object()
    embedding_model = object()
    es_client = object()
    es_store = SimpleNamespace(client=es_client)

    monkeypatch.setattr(session_module, "init_engine", fake_init_engine)
    monkeypatch.setattr(session_module, "close_engine", fake_close_engine)
    monkeypatch.setattr(session_module, "get_session_factory", fake_get_session_factory)
    monkeypatch.setattr("app.domains.document.repositories.document_repository.DocumentRepository", FakeRepository)
    monkeypatch.setattr("app.infrastructure.redis_lock.create_redis_client", lambda url: FakeRedis())
    monkeypatch.setattr("app.infrastructure.minio.get_minio_client", lambda: minio_client)
    monkeypatch.setattr("app.infrastructure.minio.ensure_minio_bucket", fake_ensure_minio_bucket)
    monkeypatch.setattr("app.domains.document.components.storage.DocumentObjectStorage", FakeStorage)
    monkeypatch.setattr("app.infrastructure.mineru.create_mineru_client", lambda cfg: mineru_client)
    monkeypatch.setattr(
        kafka_worker,
        "create_runtime_image_describer",
        lambda cfg: image_describer,
        raising=False,
    )
    monkeypatch.setattr(
        "app.domains.document.components.vector_store.create_embedding_model",
        lambda cfg: embedding_model,
    )
    monkeypatch.setattr(
        "app.domains.document.components.vector_store.create_elasticsearch_store",
        lambda *, settings, embedding_model: es_store,
    )
    monkeypatch.setattr(
        "app.domains.document.components.vector_store.ElasticsearchVectorStoreAdapter",
        FakeAdapter,
    )

    async with kafka_worker.RuntimeResourceStack() as stack:
        worker_runtime = await kafka_worker.create_kafka_worker_runtime(
            stack=stack,
            settings=settings,
        )

    assert worker_runtime.settings is settings
    assert worker_runtime.session_factory == "session-factory"
    assert isinstance(worker_runtime.conversion.repository, FakeRepository)
    assert isinstance(worker_runtime.conversion.redis_client, FakeRedis)
    assert worker_runtime.conversion.storage.bucket == "documents"
    assert worker_runtime.conversion.mineru_client is mineru_client
    assert worker_runtime.conversion.image_describer is image_describer
    assert worker_runtime.vector_storage.repository is worker_runtime.conversion.repository
    assert worker_runtime.vector_storage.redis_client is worker_runtime.conversion.redis_client
    assert worker_runtime.vector_storage.embedding_model is embedding_model
    assert worker_runtime.vector_storage.vector_store.store is es_store
    assert worker_runtime.conversion.lock_expire_seconds == 120
    assert worker_runtime.vector_storage.lock_expire_seconds == 120


def test_runtime_module_does_not_own_kafka_worker_host_context_manager():
    from app.entrypoints import document_worker as kafka_worker

    source = inspect.getsource(kafka_worker)

    assert not hasattr(kafka_worker, "kafka_worker_runtime")
    assert "_create_document_worker_runtime" not in source


@pytest.mark.asyncio
async def test_celery_worker_runtime_groups_startup_document_resources(monkeypatch):
    from app.entrypoints import celery_worker

    calls = []
    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://db/app",
        redis_url="redis://redis.example:6379/0",
        minio_bucket="documents",
        minio_public_base_url="https://files.example.com",
        elasticsearch_index="doc-vectors",
        document_convert_lock_expire_seconds=120,
    )
    repository = object()
    redis_client = object()
    storage = object()
    mineru_client = object()
    image_describer = object()
    vector_store = object()

    async def fake_initialize_runtime_database(*, stack, settings):
        calls.append(("init_db", settings.database_url))
        return "session-factory"

    monkeypatch.setattr(
        celery_worker,
        "initialize_runtime_database",
        fake_initialize_runtime_database,
    )
    monkeypatch.setattr(celery_worker, "_create_worker_repository", lambda session_factory: repository)
    monkeypatch.setattr(celery_worker, "_create_worker_redis_client", lambda stack, settings: redis_client)
    monkeypatch.setattr(celery_worker, "_create_worker_document_storage", lambda settings: storage)
    monkeypatch.setattr(
        celery_worker,
        "_create_worker_mineru_client",
        lambda stack, settings: mineru_client,
    )
    monkeypatch.setattr(
        celery_worker,
        "_create_worker_image_describer",
        lambda stack, settings: image_describer,
    )
    monkeypatch.setattr(
        celery_worker,
        "_create_worker_vector_store",
        lambda stack, settings, embedding_model: vector_store,
    )
    monkeypatch.setattr(celery_worker, "_create_worker_embedding_model", lambda settings: object())

    async with celery_worker.RuntimeResourceStack() as stack:
        created_runtime = await celery_worker.create_celery_worker_runtime(
            stack=stack,
            settings=settings,
        )

    assert created_runtime.settings is settings
    assert created_runtime.session_factory == "session-factory"
    assert created_runtime.compensation.repository is repository
    assert created_runtime.compensation.storage is storage
    assert created_runtime.compensation.mineru_client is mineru_client
    assert created_runtime.compensation.image_describer is image_describer
    assert created_runtime.compensation.vector_storage.repository is repository
    assert created_runtime.compensation.vector_storage.redis_client is redis_client
    assert created_runtime.compensation.vector_storage.vector_store is vector_store
    assert created_runtime.compensation.vector_storage.lock_expire_seconds == 120
    assert calls == [("init_db", "postgresql+asyncpg://db/app")]


def test_api_deps_avoid_redundant_document_app_state_getters():
    from app.services.document_api import deps

    assert not hasattr(deps, "DbSession")
    assert not hasattr(deps, "_require")
    assert not hasattr(deps, "get_document_repository")
    assert not hasattr(deps, "get_document_storage")
    assert not hasattr(deps, "get_document_file_detector")


def test_api_deps_assemble_settings_and_document_dependency_state():
    from app.services.document_api import deps

    source = inspect.getsource(deps)
    assert "def get_config(request: Request)" in source
    assert "UploadLimits" not in source
    assert "def get_document_deps(" in source
    assert "def get_api_runtime(" not in source
    assert "async def application_lifespan_resources" in source
    assert "async def api_runtime" not in source
    assert "async def document_runtime" not in source
    assert "document_upload_runtime" not in source
    assert "initialize_database_deps(" in source
    assert "DocumentRepository(session_factory)" in source
    assert "DocumentApiDeps(" in source
    assert "ApiRuntime(" not in source
    assert "application.state.settings" in source
    assert "application.state.api_runtime" not in source
    assert "application.state.document_deps" in source
    assert "DocumentObjectStorage(" in source
    assert "get_minio_client()" in source
    assert "ensure_minio_bucket(" in source
    assert "get_magika_client()" in source
    assert "SnowflakeIdGenerator(worker_id=settings.snowflake_worker_id)" in source
    assert "KafkaDocumentConversionDispatcher(" in source
    assert "KafkaDocumentEmbedStoreDispatcher(" in source
    assert "create_default_document_splitter_factory()" in source
    assert "create_kafka_producer(" in source
    assert "create_redis_client(" in source
    assert "push_async_callback(close_engine)" not in source


@pytest.mark.asyncio
async def test_application_lifespan_resources_close_engine_when_startup_fails(monkeypatch):
    from app.services.document_api import deps

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

    monkeypatch.setattr("app.infrastructure.db.session.init_engine", fake_init_engine)
    monkeypatch.setattr("app.infrastructure.db.session.close_engine", fake_close_engine)
    monkeypatch.setattr("app.infrastructure.db.session.get_session_factory", fake_get_session_factory)
    monkeypatch.setattr(
        "app.domains.document.repositories.document_repository.DocumentRepository",
        FakeDocumentRepository,
    )
    monkeypatch.setattr("app.infrastructure.minio.get_minio_client", explode_minio_client)

    app = SimpleNamespace(state=SimpleNamespace())
    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://user:pass@localhost:5432/app",
        minio_bucket="documents",
        minio_public_base_url="https://files.example.com",
        kafka_bootstrap_servers="kafka.example:9092",
        mineru_base_url="https://mineru.example.com",
        mineru_timeout_seconds=30,
        snowflake_worker_id=7,
    )

    with pytest.raises(RuntimeError, match="minio unavailable"):
        async with deps.application_lifespan_resources(app, settings):
            pass

    assert calls == [
        ("init_engine", "postgresql+asyncpg://user:pass@localhost:5432/app"),
        ("close_engine", None),
    ]
    assert not hasattr(app.state, "settings")
    assert not hasattr(app.state, "document_deps")


@pytest.mark.asyncio
async def test_application_lifespan_resources_assemble_document_deps_before_serving(monkeypatch):
    from app.services.document_api import deps

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

    class FakeKafkaDocumentConversionDispatcher:
        def __init__(self, producer):
            calls.append(("create_dispatcher", producer))

    class FakeKafkaDocumentEmbedStoreDispatcher:
        def __init__(self, producer):
            calls.append(("create_embed_store_dispatcher", producer))

    def fake_create_default_document_splitter_factory():
        calls.append(("create_splitter_factory", None))
        return "splitter-factory"

    class FakeRedisClient:
        def close(self):
            calls.append(("redis_close", None))

    def fake_create_redis_client(redis_url):
        calls.append(("create_redis_client", redis_url))
        return FakeRedisClient()

    monkeypatch.setattr("app.infrastructure.db.session.init_engine", fake_init_engine)
    monkeypatch.setattr("app.infrastructure.db.session.close_engine", fake_close_engine)
    monkeypatch.setattr("app.infrastructure.db.session.get_session_factory", fake_get_session_factory)
    monkeypatch.setattr(
        "app.domains.document.repositories.document_repository.DocumentRepository",
        FakeDocumentRepository,
    )
    minio_client = object()
    monkeypatch.setattr("app.infrastructure.minio.get_minio_client", lambda: minio_client)
    monkeypatch.setattr("app.infrastructure.minio.ensure_minio_bucket", fake_ensure_minio_bucket)
    monkeypatch.setattr("app.infrastructure.magika.get_magika_client", lambda: object())
    monkeypatch.setattr(
        "app.domains.document.components.storage.DocumentObjectStorage",
        FakeDocumentObjectStorage,
    )
    monkeypatch.setattr(
        "app.infrastructure.snowflake.SnowflakeIdGenerator",
        FakeSnowflakeIdGenerator,
    )
    monkeypatch.setattr("app.infrastructure.kafka.create_kafka_producer", lambda bootstrap_servers: "producer")
    monkeypatch.setattr("app.infrastructure.redis_lock.create_redis_client", fake_create_redis_client)
    monkeypatch.setattr(
        "app.domains.document.components.dispatcher.KafkaDocumentConversionDispatcher",
        FakeKafkaDocumentConversionDispatcher,
    )
    monkeypatch.setattr(
        "app.domains.document.components.dispatcher.KafkaDocumentEmbedStoreDispatcher",
        FakeKafkaDocumentEmbedStoreDispatcher,
    )
    monkeypatch.setattr(
        "app.domains.document.components.splitters.create_default_document_splitter_factory",
        fake_create_default_document_splitter_factory,
    )

    app = SimpleNamespace(state=SimpleNamespace())
    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://user:pass@localhost:5432/app",
        minio_bucket="documents",
        minio_public_base_url="https://files.example.com",
        redis_url="redis://redis.example:6379/0",
        kafka_bootstrap_servers="kafka.example:9092",
        mineru_base_url="https://mineru.example.com",
        mineru_timeout_seconds=30,
        snowflake_worker_id=7,
    )

    async with deps.application_lifespan_resources(app, settings):
        assert calls == [
            ("init_engine", "postgresql+asyncpg://user:pass@localhost:5432/app"),
            ("ensure_minio_bucket", "documents"),
            ("create_redis_client", "redis://redis.example:6379/0"),
            ("create_storage", "documents"),
            ("create_id_generator", 7),
            ("create_dispatcher", "producer"),
            ("create_embed_store_dispatcher", "producer"),
            ("create_splitter_factory", None),
        ]
        assert app.state.settings is settings
        assert not hasattr(app.state, "api_runtime")
        assert app.state.document_deps.storage.bucket == "documents"
        assert isinstance(app.state.document_deps.repository, FakeDocumentRepository)
        assert app.state.document_deps.embed_store_dispatcher is not None
        assert app.state.document_deps.splitter_factory == "splitter-factory"
        assert app.state.document_deps.redis_client is not None
        assert not hasattr(app.state.document_deps, "settings")
        assert not hasattr(app.state.document_deps, "session_factory")

    assert not hasattr(app.state, "settings")
    assert not hasattr(app.state, "document_deps")
    assert calls[-2:] == [
        ("redis_close", None),
        ("close_engine", None),
    ]


def test_document_router_reads_config_through_api_deps():
    from app.services.document_api import document_router as router

    source = inspect.getsource(router)
    assert "get_config" in source
    assert "Depends(get_config)" in source
    assert "max_upload_size_mb=settings.max_upload_size_mb" in source
    assert "UploadLimits" not in source
    assert "get_settings()" not in source


def test_document_router_reads_document_deps_through_api_deps():
    from app.services.document_api import document_router as router

    source = inspect.getsource(router)
    assert "from app.services.document_api.deps import" in source
    assert "from app.runtime import" not in source
    assert "Depends(get_document_deps)" in source
    assert "request.app.state" not in source
    assert "document_deps" in source
    assert "DocumentApiDeps" in source
    assert "ApiRuntime" not in source
    assert "get_document_repository" not in source
    assert "get_document_storage" not in source
    assert "get_document_file_detector" not in source


def test_process_runtime_is_not_exported_from_document_module():
    import importlib.util

    assert importlib.util.find_spec("app.runtime") is None
    assert importlib.util.find_spec("app.modules") is None
    assert importlib.util.find_spec("app.services.document_api.runtime") is None


def test_runtime_owner_modules_do_not_import_global_runtime_module():
    from app.services.document_api import deps
    from app.services.document_api import document_router as router
    from app.domains.document.tasks import vector_storage_compensation
    from app.domains.document.workers import conversion_consumer as conversion, vectorization_consumer as vector_storage
    from app.entrypoints import celery_worker, document_worker as kafka_worker

    for module in [
        deps,
        router,
        conversion,
        vector_storage,
        vector_storage_compensation,
        kafka_worker,
        celery_worker,
    ]:
        assert "app.runtime" not in inspect.getsource(module)


def test_worker_type_checking_imports_document_cycle_prevention_comment():
    from app.domains.document.tasks import vector_storage_compensation
    from app.domains.document.workers import conversion_consumer as conversion, vectorization_consumer as vector_storage

    for module in [conversion, vector_storage, vector_storage_compensation]:
        source = inspect.getsource(module)
        snippet = source[source.index("if TYPE_CHECKING:") : source.index("logger =")]

        assert "仅用于类型检查" in snippet
        assert "避免运行时导入" in snippet
        assert "循环依赖" in snippet


def test_document_api_app_owns_document_router_and_lifespan_deps():
    from app.services.document_api import app

    source = inspect.getsource(app)
    assert "from app.api" not in source
    assert "from app.services.document_api.router import router" in source
    assert "lifespan=" in source
    assert "from app.services.document_api.deps import application_lifespan_resources" in source
    assert "async with application_lifespan_resources(application, startup_settings)" in source
    assert "api_runtime" not in source
    assert "document_runtime" not in source
    assert "document_deps" not in source
    assert "document_upload_runtime" not in source
    for implementation_detail in [
        "init_engine",
        "DocumentRepository",
        "DocumentObjectStorage",
        "get_minio_client",
        "get_magika_client",
    ]:
        assert implementation_detail not in source


def test_agent_api_app_does_not_own_document_deps():
    from app.services.agent_api import app

    source = inspect.getsource(app)
    assert "from app.api" not in source
    assert "from app.services.agent_api.router import router" in source
    assert "application_lifespan_resources" not in source
    assert "document_runtime" not in source
    assert "document_deps" not in source
    assert "DocumentRepository" not in source
