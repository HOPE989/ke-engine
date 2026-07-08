import pytest
from httpx import ASGITransport, AsyncClient

from app.core import config
from app.services.agent_api.app import create_app
from app.domains.agent.services import chat as chat_service_module


@pytest.mark.asyncio
async def test_chat_returns_non_empty_answer_from_mocked_langchain_client(tmp_path, monkeypatch):
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
            return type("FakeMessage", (), {"content": "mocked endpoint answer"})()

    monkeypatch.setattr(chat_service_module, "ChatOpenAI", FakeChatOpenAI)

    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "Reply with one short sentence."},
        )

    config.get_settings.cache_clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["message"] == "success"
    assert payload["data"]["answer"] == "mocked endpoint answer"
