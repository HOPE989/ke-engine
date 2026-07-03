import importlib.util
import inspect
from pathlib import Path

from app.core import config


DOCUMENT_ENV_LINES = [
    "DATABASE_URL=postgresql+asyncpg://user:pass@db.example:5432/app",
    "MINIO_ACCESS_KEY=minio-access",
    "MINIO_SECRET_KEY=minio-secret",
    "MINERU_API_KEY=mineru-key",
    "OPENAI_API_KEY=openai-key",
]


DOCUMENT_CONFIG_YAML = """
max_upload_size_mb: 25
minio_endpoint: minio.example:9000
minio_bucket: documents
minio_public_base_url: https://files.example.com
minio_secure: true
mineru_base_url: https://mineru.example.com
mineru_provider: official
mineru_model_version: vlm
mineru_poll_interval_seconds: 2
mineru_poll_timeout_seconds: 120
mineru_timeout_seconds: 45
redis_url: redis://redis.example:6379/3
kafka_bootstrap_servers: kafka.example:9092
document_convert_lock_expire_seconds: 180
snowflake_worker_id: 7
openai_base_url: https://openai.example.com/v1
openai_model: test-model
"""


def test_document_settings_load_from_env_and_config_yaml(tmp_path, monkeypatch):
    env_file = tmp_path / "backend.env"
    config_file = tmp_path / "config.yaml"
    env_file.write_text("\n".join(DOCUMENT_ENV_LINES), encoding="utf-8")
    config_file.write_text(DOCUMENT_CONFIG_YAML, encoding="utf-8")
    for line in DOCUMENT_ENV_LINES:
        monkeypatch.delenv(line.split("=", 1)[0], raising=False)

    settings = config.create_settings(env_file=env_file, config_file=config_file)

    assert settings.database_url == "postgresql+asyncpg://user:pass@db.example:5432/app"
    assert settings.max_upload_size_mb == 25
    assert settings.minio_endpoint == "minio.example:9000"
    assert settings.minio_access_key == "minio-access"
    assert settings.minio_secret_key == "minio-secret"
    assert settings.minio_bucket == "documents"
    assert settings.minio_public_base_url == "https://files.example.com"
    assert settings.minio_secure is True
    assert settings.mineru_base_url == "https://mineru.example.com"
    assert settings.mineru_provider == "official"
    assert settings.mineru_api_key == "mineru-key"
    assert settings.mineru_model_version == "vlm"
    assert settings.mineru_poll_interval_seconds == 2
    assert settings.mineru_poll_timeout_seconds == 120
    assert settings.mineru_timeout_seconds == 45
    assert settings.redis_url == "redis://redis.example:6379/3"
    assert settings.kafka_bootstrap_servers == "kafka.example:9092"
    assert settings.document_convert_lock_expire_seconds == 180
    assert settings.snowflake_worker_id == 7
    assert settings.openai_api_key == "openai-key"
    assert settings.openai_base_url == "https://openai.example.com/v1"
    assert settings.openai_model == "test-model"


def test_process_environment_overrides_config_yaml(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("max_upload_size_mb: 25\n", encoding="utf-8")
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "99")

    settings = config.create_settings(config_file=config_file)

    assert settings.max_upload_size_mb == 99


def test_env_example_documents_user_required_and_secret_configuration_names():
    env_example = Path(config.BACKEND_DIR, ".env.example").read_text(encoding="utf-8")

    for name in [
        "DATABASE_URL",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "MINERU_API_KEY",
        "OPENAI_API_KEY",
    ]:
        assert f"{name}=" in env_example

    for name in [
        "MAX_UPLOAD_SIZE_MB",
        "MINIO_ENDPOINT",
        "MINIO_BUCKET",
        "MINIO_PUBLIC_BASE_URL",
        "MINIO_SECURE",
        "MINERU_BASE_URL",
        "MINERU_PROVIDER",
        "MINERU_MODEL_VERSION",
        "MINERU_POLL_INTERVAL_SECONDS",
        "MINERU_POLL_TIMEOUT_SECONDS",
        "MINERU_TIMEOUT_SECONDS",
        "REDIS_URL",
        "KAFKA_BOOTSTRAP_SERVERS",
        "DOCUMENT_CONVERT_LOCK_EXPIRE_SECONDS",
        "SNOWFLAKE_WORKER_ID",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
    ]:
        assert f"{name}=" not in env_example


def test_config_yaml_documents_non_secret_runtime_defaults():
    config_yaml = Path(config.BACKEND_DIR, "config.yaml").read_text(encoding="utf-8")

    for name in [
        "max_upload_size_mb",
        "minio_endpoint",
        "minio_bucket",
        "minio_public_base_url",
        "minio_secure",
        "mineru_base_url",
        "mineru_provider",
        "mineru_model_version",
        "mineru_poll_interval_seconds",
        "mineru_poll_timeout_seconds",
        "mineru_timeout_seconds",
        "redis_url",
        "kafka_bootstrap_servers",
        "document_convert_lock_expire_seconds",
        "snowflake_worker_id",
        "openai_base_url",
        "openai_model",
    ]:
        assert f"{name}:" in config_yaml

    for name in [
        "database_url",
        "minio_access_key",
        "minio_secret_key",
        "mineru_api_key",
        "openai_api_key",
    ]:
        assert f"{name}:" not in config_yaml


def test_document_upload_dependencies_are_available():
    for module_name in [
        "alembic",
        "confluent_kafka",
        "minio",
        "magika",
        "multipart",
        "redis",
        "redis_lock",
    ]:
        assert importlib.util.find_spec(module_name) is not None


def test_document_chunking_dependencies_are_available():
    from langchain_text_splitters import (
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )

    assert MarkdownHeaderTextSplitter.__name__ == "MarkdownHeaderTextSplitter"
    assert RecursiveCharacterTextSplitter.__name__ == "RecursiveCharacterTextSplitter"


def test_settings_document_startup_and_request_time_boundaries():
    assert config.STARTUP_ONLY_SETTINGS == {
        "database_url",
        "minio_endpoint",
        "minio_access_key",
        "minio_secret_key",
        "minio_bucket",
        "minio_public_base_url",
        "minio_secure",
        "mineru_base_url",
        "mineru_provider",
        "mineru_api_key",
        "mineru_model_version",
        "mineru_poll_interval_seconds",
        "mineru_poll_timeout_seconds",
        "mineru_timeout_seconds",
        "redis_url",
        "kafka_bootstrap_servers",
        "document_convert_lock_expire_seconds",
        "snowflake_worker_id",
    }
    assert config.REQUEST_TIME_SETTINGS == {"max_upload_size_mb"}

    for field_name in config.STARTUP_ONLY_SETTINGS:
        description = config.Settings.model_fields[field_name].description or ""
        assert description.startswith("startup-only:")

    for field_name in config.REQUEST_TIME_SETTINGS:
        description = config.Settings.model_fields[field_name].description or ""
        assert description.startswith("request-time:")


def test_api_get_config_uses_request_time_settings_loader():
    from app.api import deps

    source = inspect.getsource(deps.get_config)

    assert "get_request_settings()" in source
