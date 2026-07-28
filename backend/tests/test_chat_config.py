import importlib.util

import pytest

from app.core import config


def test_chat_runtime_dependencies_are_available():
    for module_name in ["langgraph", "langgraph.checkpoint.postgres", "psycopg_pool"]:
        assert importlib.util.find_spec(module_name) is not None


def test_openai_model_is_startup_only_but_not_globally_required():
    settings = config.Settings(openai_model=None)

    assert settings.openai_model is None
    assert "openai_model" in config.STARTUP_ONLY_SETTINGS
    description = config.Settings.model_fields["openai_model"].description or ""
    assert description.startswith("startup-only:")


def test_chat_startup_validation_requires_configured_model():
    with pytest.raises(ValueError, match="OPENAI_MODEL"):
        config.validate_chat_startup_settings(config.Settings(openai_model=None))

    settings = config.Settings(openai_model="gpt-test")

    assert config.validate_chat_startup_settings(settings) is settings


def test_chat_has_one_rag_mcp_url_startup_setting():
    settings = config.Settings()

    assert settings.rag_mcp_url == "http://127.0.0.1:8002/mcp"
    assert "rag_mcp_url" in config.STARTUP_ONLY_SETTINGS
    assert [
        name
        for name in config.Settings.model_fields
        if name.startswith("rag_mcp")
    ] == ["rag_mcp_url"]
