from pathlib import Path

from app.core import config


def test_document_settings_read_documented_environment_names(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql+asyncpg://doc:doc@localhost:5432/doc",
                "MAX_UPLOAD_SIZE_MB=25",
                "MINIO_ENDPOINT=minio.test:9000",
                "MINIO_ACCESS_KEY=test-access",
                "MINIO_SECRET_KEY=test-secret",
                "MINIO_BUCKET=test-documents",
                "MINIO_PUBLIC_BASE_URL=https://files.example.test",
                "MINIO_SECURE=true",
                "MINERU_BASE_URL=http://mineru.test",
                "MINERU_TIMEOUT_SECONDS=30",
            ]
        ),
        encoding="utf-8",
    )
    for name in (
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
    ):
        monkeypatch.delenv(name, raising=False)

    settings = config.create_settings(env_file=env_file)

    assert settings.database_url == "postgresql+asyncpg://doc:doc@localhost:5432/doc"
    assert settings.max_upload_size_mb == 25
    assert settings.minio_endpoint == "minio.test:9000"
    assert settings.minio_access_key == "test-access"
    assert settings.minio_secret_key == "test-secret"
    assert settings.minio_bucket == "test-documents"
    assert settings.minio_public_base_url == "https://files.example.test"
    assert settings.minio_secure is True
    assert settings.mineru_base_url == "http://mineru.test"
    assert settings.mineru_timeout_seconds == 30


def test_backend_env_example_documents_document_upload_settings():
    env_example = Path(config.BACKEND_DIR) / ".env.example"

    content = env_example.read_text(encoding="utf-8")

    for name in (
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
    ):
        assert f"{name}=" in content
