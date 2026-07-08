from pathlib import Path
import pkgutil

import app.contracts


def _backend_app_root() -> Path:
    return Path(__file__).resolve().parents[1] / "app"


def test_target_architecture_files_exist():
    app_root = _backend_app_root()
    expected_files = [
        "entrypoints/document_api.py",
        "entrypoints/agent_api.py",
        "entrypoints/document_worker.py",
        "entrypoints/celery_worker.py",
        "services/document_api/app.py",
        "services/document_api/router.py",
        "services/document_api/deps.py",
        "services/agent_api/app.py",
        "services/agent_api/router.py",
        "services/agent_api/deps.py",
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
        "domains/document/repositories/document_repository.py",
        "domains/document/repositories/segment_repository.py",
        "domains/document/repositories/table_repository.py",
        "domains/document/shared/models.py",
        "domains/document/shared/schemas.py",
        "domains/document/shared/errors.py",
        "domains/document/shared/file_types.py",
        "domains/document/workers/conversion_consumer.py",
        "domains/document/workers/vectorization_consumer.py",
        "domains/agent/services/conversation.py",
        "domains/agent/services/orchestration.py",
        "domains/agent/services/retrieval.py",
        "domains/agent/services/tool_calling.py",
        "domains/agent/services/memory.py",
        "domains/agent/components/prompts.py",
        "domains/agent/components/context_builder.py",
        "domains/agent/components/response_streaming.py",
        "domains/agent/components/reranker.py",
        "domains/agent/repositories/conversation_repository.py",
        "domains/agent/repositories/message_repository.py",
        "domains/agent/shared/errors.py",
        "contracts/document/http.py",
        "contracts/document/events.py",
        "contracts/agent/http.py",
        "contracts/agent/events.py",
        "contracts/agent/mcp.py",
        "contracts/identity/http.py",
        "infrastructure/db/session.py",
        "infrastructure/db/base.py",
        "infrastructure/kafka.py",
        "infrastructure/redis.py",
        "infrastructure/minio.py",
        "infrastructure/elasticsearch.py",
        "infrastructure/llm.py",
        "infrastructure/celery_app.py",
        "core/config.py",
        "core/logging.py",
        "core/exceptions.py",
        "core/security.py",
        "common/response.py",
        "common/pagination.py",
        "common/enums.py",
    ]

    missing = [path for path in expected_files if not (app_root / path).is_file()]

    assert missing == []


def test_target_architecture_public_imports_are_available():
    from app.domains.agent.services.conversation import chat
    from app.domains.document.components.segment_builder import build_segment_drafts
    from app.domains.document.components.storage_keys import original_object_key
    from app.domains.document.components.validators import validate_document_upload
    from app.domains.document.repositories.segment_repository import SegmentRepository
    from app.domains.document.repositories.table_repository import TableRepository
    from app.entrypoints import agent_api, celery_worker, document_api, document_worker
    from app.infrastructure.db.session import get_session_factory
    from app.contracts.agent.http import ChatRequest
    from app.contracts.agent.mcp import ToolInvocation
    from app.contracts.document.events import DocumentConvertRequested
    from app.contracts.document.http import DocumentMetadata
    from app.contracts.identity.http import IdentityPrincipal
    from app.services.agent_api.deps import AgentApiDeps
    from app.services.document_api.deps import DocumentApiDeps

    assert agent_api.app
    assert document_api.app
    assert callable(document_worker.main)
    assert celery_worker.celery_app
    assert callable(chat)
    assert callable(build_segment_drafts)
    assert callable(original_object_key)
    assert callable(validate_document_upload)
    assert SegmentRepository
    assert TableRepository
    assert callable(get_session_factory)
    assert ChatRequest
    assert ToolInvocation
    assert DocumentConvertRequested
    assert DocumentMetadata
    assert IdentityPrincipal
    assert AgentApiDeps
    assert DocumentApiDeps


def test_service_api_layers_do_not_keep_runtime_or_error_mapping_shells():
    app_root = _backend_app_root()

    assert not (app_root / "services" / "document_api" / "runtime.py").exists()
    assert not (app_root / "services" / "document_api" / "error_mapping.py").exists()
    assert not (app_root / "services" / "agent_api" / "runtime.py").exists()
    assert not (app_root / "services" / "agent_api" / "error_mapping.py").exists()


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
    assert (app_root / "contracts" / "agent").is_dir()
    assert (app_root / "contracts" / "identity").is_dir()


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
