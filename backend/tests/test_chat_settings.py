from app.core import config


def test_create_settings_reads_explicit_env_file_without_current_working_directory(
    tmp_path,
    monkeypatch,
):
    explicit_env = tmp_path / "backend.env"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    explicit_env.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=test-key",
                "OPENAI_BASE_URL=https://example.test/v1",
                "OPENAI_MODEL=test-model",
            ]
        ),
        encoding="utf-8",
    )
    (runtime_dir / ".env").write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=wrong-key",
                "OPENAI_BASE_URL=https://wrong.example/v1",
                "OPENAI_MODEL=wrong-model",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.chdir(runtime_dir)

    settings = config.create_settings(env_file=explicit_env)

    assert settings.openai_api_key == "test-key"
    assert settings.openai_base_url == "https://example.test/v1"
    assert settings.openai_model == "test-model"


def test_settings_reads_backend_dotenv_independent_of_current_working_directory(
    tmp_path,
    monkeypatch,
):
    backend_env = tmp_path / "backend.env"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    backend_env.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=test-key",
                "OPENAI_BASE_URL=https://example.test/v1",
                "OPENAI_MODEL=test-model",
            ]
        ),
        encoding="utf-8",
    )
    (runtime_dir / ".env").write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=wrong-key",
                "OPENAI_BASE_URL=https://wrong.example/v1",
                "OPENAI_MODEL=wrong-model",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", backend_env)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.chdir(runtime_dir)
    config.get_settings.cache_clear()

    settings = config.get_settings()

    assert settings.openai_api_key == "test-key"
    assert settings.openai_base_url == "https://example.test/v1"
    assert settings.openai_model == "test-model"
