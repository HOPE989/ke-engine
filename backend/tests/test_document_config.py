import importlib.util
import inspect
from pathlib import Path

from app.core import config


DOCUMENT_ENV_LINES = [
    "DATABASE_URL=postgresql+asyncpg://user:pass@db.example:5432/app",
    "MAX_UPLOAD_SIZE_MB=25",
    "MINIO_ENDPOINT=minio.example:9000",
    "MINIO_ACCESS_KEY=minio-access",
    "MINIO_SECRET_KEY=minio-secret",
    "MINIO_BUCKET=documents",
    "MINIO_PUBLIC_BASE_URL=https://files.example.com",
    "MINIO_SECURE=true",
    "MINERU_BASE_URL=https://mineru.example.com",
    "MINERU_PROVIDER=official",
    "MINERU_API_KEY=mineru-key",
    "MINERU_MODEL_VERSION=vlm",
    "MINERU_POLL_INTERVAL_SECONDS=2",
    "MINERU_POLL_TIMEOUT_SECONDS=120",
    "MINERU_TIMEOUT_SECONDS=45",
    "REDIS_URL=redis://redis.example:6379/3",
    "KAFKA_BOOTSTRAP_SERVERS=kafka.example:9092",
    "DOCUMENT_CONVERT_LOCK_EXPIRE_SECONDS=180",
    "SNOWFLAKE_WORKER_ID=7",
    "OPENAI_API_KEY=openai-key",
    "OPENAI_BASE_URL=https://openai.example.com/v1",
    "OPENAI_MODEL=test-model",
]


def test_document_settings_load_from_backend_env_style_names(tmp_path, monkeypatch):
    env_file = tmp_path / "backend.env"
    env_file.write_text("\n".join(DOCUMENT_ENV_LINES), encoding="utf-8")
    for line in DOCUMENT_ENV_LINES:
        monkeypatch.delenv(line.split("=", 1)[0], raising=False)

    settings = config.create_settings(env_file=env_file)

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


def test_env_example_documents_document_upload_configuration_names():
    env_example = Path(config.BACKEND_DIR, ".env.example").read_text(encoding="utf-8")

    for name in [
        "DATABASE_URL",
        "MAX_UPLOAD_SIZE_MB",
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "MINIO_BUCKET",
        "MINIO_PUBLIC_BASE_URL",
        "MINIO_SECURE",
        "MINERU_BASE_URL",
        "MINERU_PROVIDER",
        "MINERU_API_KEY",
        "MINERU_MODEL_VERSION",
        "MINERU_POLL_INTERVAL_SECONDS",
        "MINERU_POLL_TIMEOUT_SECONDS",
        "MINERU_TIMEOUT_SECONDS",
        "REDIS_URL",
        "KAFKA_BOOTSTRAP_SERVERS",
        "DOCUMENT_CONVERT_LOCK_EXPIRE_SECONDS",
        "SNOWFLAKE_WORKER_ID",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
    ]:
        assert f"{name}=" in env_example


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
