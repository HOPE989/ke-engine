import pytest
from fastapi import status

from app.core import config
from app.core.exceptions import AppException
from app.modules.chat import service as chat_service_module
from app.modules.chat.service import ChatService


@pytest.mark.asyncio
async def test_chat_service_rejects_missing_openai_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)
    config.get_settings.cache_clear()

    with pytest.raises(AppException) as exc_info:
        await ChatService().chat("hello")

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "OPENAI_API_KEY" in exc_info.value.message


@pytest.mark.asyncio
async def test_chat_service_rejects_blank_openai_api_key(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=   \n", encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)
    config.get_settings.cache_clear()

    with pytest.raises(AppException) as exc_info:
        await ChatService().chat("hello")

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "OPENAI_API_KEY" in exc_info.value.message


def test_chat_service_defaults_blank_model_name(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=test-key\nOPENAI_MODEL=   \n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)
    config.get_settings.cache_clear()

    model = ChatService()._create_chat_model()

    assert model.model_name == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_chat_service_returns_mocked_llm_answer(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)
    config.get_settings.cache_clear()

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def ainvoke(self, message: str):
            assert message == "Reply with one short sentence."
            return type("FakeMessage", (), {"content": "mocked answer"})()

    monkeypatch.setattr(chat_service_module, "ChatOpenAI", FakeChatOpenAI)

    answer = await ChatService().chat("Reply with one short sentence.")

    assert answer == "mocked answer"


@pytest.mark.asyncio
async def test_chat_service_reuses_chat_model_between_calls(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)
    config.get_settings.cache_clear()
    created_models = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            created_models.append(kwargs)

        async def ainvoke(self, message: str):
            return type("FakeMessage", (), {"content": f"answer: {message}"})()

    monkeypatch.setattr(chat_service_module, "ChatOpenAI", FakeChatOpenAI)
    service = ChatService()

    first_answer = await service.chat("first")
    second_answer = await service.chat("second")

    assert first_answer == "answer: first"
    assert second_answer == "answer: second"
    assert created_models == [{"api_key": "test-key", "model": "gpt-4o-mini"}]


@pytest.mark.asyncio
async def test_chat_service_provider_failure_raises_app_exception_without_secret(
    tmp_path,
    monkeypatch,
):
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=test-secret-value",
                "OPENAI_BASE_URL=http://127.0.0.1:9/v1",
                "OPENAI_MODEL=gpt-4o-mini",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)
    config.get_settings.cache_clear()

    with pytest.raises(AppException) as exc_info:
        await ChatService().chat("hello")

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert "chat provider request failed" in exc_info.value.message
    assert "test-secret-value" not in exc_info.value.message
