import importlib.util
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
    "MINERU_TIMEOUT_SECONDS=45",
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
    assert settings.mineru_timeout_seconds == 45


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
        "MINERU_TIMEOUT_SECONDS",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
    ]:
        assert f"{name}=" in env_example


def test_document_upload_dependencies_are_available():
    for module_name in ["alembic", "minio", "magika", "multipart"]:
        assert importlib.util.find_spec(module_name) is not None
