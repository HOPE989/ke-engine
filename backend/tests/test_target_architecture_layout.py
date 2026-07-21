from pathlib import Path
import pkgutil

import app.contracts


def _backend_app_root() -> Path:
    return Path(__file__).resolve().parents[1] / "app"


def test_target_architecture_files_exist():
    app_root = _backend_app_root()
    expected_files = [
        "entrypoints/document_api.py",
        "entrypoints/chat_api.py",
        "entrypoints/studio_graph.py",
        "entrypoints/document_worker.py",
        "entrypoints/celery_worker.py",
        "services/document_api/app.py",
        "services/document_api/router.py",
        "services/document_api/deps.py",
        "domains/document/services/upload.py",
        "domains/document/services/conversion.py",
        "domains/document/services/chunking.py",
        "domains/document/services/vectorization.py",
        "domains/document/services/data_query.py",
        "domains/document/components/validators.py",
        "domains/document/components/storage_keys.py",
        "domains/document/components/converters.py",
        "domains/document/components/splitters.py",
        "domains/document/components/segment_builder.py",
        "domains/document/components/markdown_assets.py",
        "domains/document/components/image_describer.py",
        "domains/document/repositories/document_repository.py",
        "domains/document/repositories/segment_repository.py",
        "domains/document/repositories/table_repository.py",
        "domains/document/shared/models.py",
        "domains/document/shared/schemas.py",
        "domains/document/shared/errors.py",
        "domains/document/shared/file_types.py",
        "domains/document/workers/conversion_consumer.py",
        "domains/document/workers/vectorization_consumer.py",
        "contracts/document/http.py",
        "contracts/document/events.py",
        "contracts/chat/__init__.py",
        "contracts/chat/http.py",
        "contracts/chat/stream.py",
        "services/chat_api/__init__.py",
        "services/chat_api/app.py",
        "services/chat_api/deps.py",
        "services/chat_api/router.py",
        "services/chat_api/streaming.py",
        "domains/chat/graph/__init__.py",
        "domains/chat/graph/builder.py",
        "domains/chat/graph/context.py",
        "domains/chat/graph/state.py",
        "domains/chat/graph/nodes/__init__.py",
        "domains/chat/graph/nodes/llm.py",
        "domains/chat/repositories/__init__.py",
        "domains/chat/repositories/conversation_repository.py",
        "domains/chat/repositories/message_repository.py",
        "domains/chat/services/__init__.py",
        "domains/chat/services/conversation.py",
        "domains/chat/services/runtime.py",
        "domains/chat/shared/models.py",
        "infrastructure/db/session.py",
        "infrastructure/db/base.py",
        "infrastructure/kafka.py",
        "infrastructure/redis.py",
        "infrastructure/minio.py",
        "infrastructure/elasticsearch.py",
        "infrastructure/llm.py",
        "infrastructure/langgraph.py",
        "infrastructure/celery_app.py",
        "core/config.py",
        "core/logging.py",
        "core/exceptions.py",
        "common/response.py",
        "common/pagination.py",
        "common/enums.py",
        "identity/__init__.py",
        "identity/principal.py",
        "identity/config.py",
        "identity/errors.py",
        "identity/dependencies.py",
        "identity/middleware.py",
        "identity/provider.py",
        "identity/providers/__init__.py",
        "identity/providers/mock.py",
        "identity/providers/portal.py",
    ]

    missing = [path for path in expected_files if not (app_root / path).is_file()]

    assert missing == []
    assert not (app_root / "infrastructure" / "redis_lock.py").exists()
    assert not (app_root / "domains" / "document" / "components" / "vector_store.py").exists()
    assert not (app_root / "contracts" / "identity").exists()
    assert not (app_root / "core" / "security.py").exists()
    for removed_path in [
        "entrypoints/agent_api.py",
        "services/agent_api",
        "domains/agent",
        "contracts/agent",
    ]:
        assert not (app_root / removed_path).exists()


def test_target_architecture_public_imports_are_available():
    from app.identity import IdentityMiddleware, MockIdentityProvider, Principal, get_current_principal
    from app.domains.document.components.segment_builder import build_segment_drafts
    from app.domains.document.components.storage_keys import original_object_key
    from app.domains.document.components.validators import validate_document_upload
    from app.domains.document.repositories.segment_repository import SegmentRepository
    from app.domains.document.repositories.table_repository import TableRepository
    from app.entrypoints import celery_worker, chat_api, document_api, document_worker
    from app.contracts.chat import CompletionRequest, MetadataPayload
    from app.domains.chat.graph import build_chat_graph
    from app.domains.chat.repositories.conversation_repository import ConversationRepository
    from app.domains.chat.repositories.message_repository import MessageRepository
    from app.domains.chat.services.runtime import CompletionProducerRegistry
    from app.infrastructure.langgraph import postgres_checkpointer
    from app.services.chat_api.deps import ChatApiDeps
    from app.infrastructure.db.session import get_session_factory
    from app.contracts.document.events import DocumentConvertRequested
    from app.contracts.document.http import DocumentMetadata
    from app.services.document_api.deps import DocumentApiDeps

    assert document_api.app
    assert chat_api.app
    assert callable(document_worker.main)
    assert celery_worker.celery_app
    assert callable(build_segment_drafts)
    assert callable(original_object_key)
    assert callable(validate_document_upload)
    assert SegmentRepository
    assert TableRepository
    assert callable(get_session_factory)
    assert DocumentConvertRequested
    assert DocumentMetadata
    assert DocumentApiDeps
    assert IdentityMiddleware
    assert MockIdentityProvider
    assert Principal
    assert callable(get_current_principal)
    assert CompletionRequest
    assert MetadataPayload
    assert callable(build_chat_graph)
    assert ConversationRepository
    assert MessageRepository
    assert CompletionProducerRegistry
    assert callable(postgres_checkpointer)
    assert ChatApiDeps


def test_chat_runtime_uses_one_database_configuration_without_checkpoint_orm():
    backend_root = _backend_app_root().parent
    app_root = _backend_app_root()
    env_example = (backend_root / ".env.example").read_text(encoding="utf-8")
    config = (backend_root / "config.yaml").read_text(encoding="utf-8")

    assert env_example.count("DATABASE_URL=") == 1
    assert "OPENAI_API_KEY=" in env_example
    assert "openai_model:" in config
    assert "CHECKPOINT_DATABASE_URL" not in env_example
    assert "LANGGRAPH_DATABASE_URL" not in env_example
    assert "checkpoint_database_url" not in config
    assert "langgraph_database_url" not in config

    production_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in app_root.rglob("*.py")
    )
    assert "MemorySaver" not in production_sources

    migrations_root = backend_root / "alembic" / "versions"
    checkpoint_migrations = [
        path
        for path in migrations_root.glob("*.py")
        if "checkpoint" in path.name.lower()
        or "langgraph" in path.name.lower()
        or "checkpoint" in path.read_text(encoding="utf-8").lower()
        or "langgraph" in path.read_text(encoding="utf-8").lower()
    ]
    assert checkpoint_migrations == []

    chat_models = (app_root / "domains" / "chat" / "shared" / "models.py").read_text(
        encoding="utf-8"
    )
    assert "checkpoint" not in chat_models.lower()


def test_service_api_layers_do_not_keep_runtime_or_error_mapping_shells():
    app_root = _backend_app_root()

    assert not (app_root / "services" / "document_api" / "runtime.py").exists()
    assert not (app_root / "services" / "document_api" / "error_mapping.py").exists()


def test_document_lifecycle_service_has_been_split_by_workflow():
    app_root = _backend_app_root()

    assert not (app_root / "domains" / "document" / "services" / "lifecycle.py").exists()
    assert (app_root / "domains" / "document" / "services" / "upload.py").is_file()
    assert (app_root / "domains" / "document" / "services" / "chunking.py").is_file()


def test_contracts_are_grouped_by_domain_not_transport():
    app_root = _backend_app_root()

    assert not (app_root / "contracts" / "http").exists()
    assert not (app_root / "contracts" / "events").exists()
    assert not (app_root / "contracts" / "mcp").exists()
    assert (app_root / "contracts" / "document").is_dir()
    assert (app_root / "contracts" / "chat").is_dir()
    assert not (app_root / "contracts" / "agent").exists()
    assert not (app_root / "contracts" / "identity").exists()


def test_contract_modules_do_not_reexport_domain_types():
    contracts_root = _backend_app_root() / "contracts"
    violations = []

    for module in pkgutil.walk_packages(app.contracts.__path__, prefix="app.contracts."):
        source_path = contracts_root / Path(*module.name.removeprefix("app.contracts.").split(".")).with_suffix(".py")
        if not source_path.is_file():
            continue
        source = source_path.read_text(encoding="utf-8")
        if "from app.domains" in source or "import app.domains" in source:
            violations.append(module.name)

    assert violations == []
