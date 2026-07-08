from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import config
from app.services.agent_api.app import create_app


def assert_error_response(payload: dict, status_code: int, message_part: str) -> None:
    assert payload["code"] == status_code
    assert message_part in payload["message"]
    assert payload["data"] is None


@pytest.fixture
async def client_without_openai_key(tmp_path, monkeypatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)
    config.get_settings.cache_clear()
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    config.get_settings.cache_clear()


@pytest.fixture
async def client_with_blank_openai_key(tmp_path, monkeypatch) -> AsyncIterator[AsyncClient]:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=   \n", encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)
    config.get_settings.cache_clear()
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    config.get_settings.cache_clear()


@pytest.fixture
async def client_with_invalid_openai_provider(tmp_path, monkeypatch) -> AsyncIterator[AsyncClient]:
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
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test", timeout=20.0) as client:
        yield client

    config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chat_endpoint_uses_exact_no_trailing_slash_path(client_without_openai_key):
    response = await client_without_openai_key.post(
        "/api/v1/chat",
        json={"message": "hello"},
    )

    assert response.status_code == 503
    assert_error_response(response.json(), 503, "OPENAI_API_KEY")


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["", "   "])
async def test_chat_rejects_blank_message_before_provider_configuration(
    client_without_openai_key,
    message,
):
    response = await client_without_openai_key.post(
        "/api/v1/chat",
        json={"message": message},
    )

    assert response.status_code == 400
    assert_error_response(response.json(), 400, "message")


@pytest.mark.asyncio
async def test_chat_rejects_missing_message_before_provider_configuration(
    client_without_openai_key,
):
    response = await client_without_openai_key.post("/api/v1/chat", json={})

    assert response.status_code == 422
    assert_error_response(response.json(), 422, "request validation failed")


@pytest.mark.asyncio
async def test_chat_rejects_non_string_message_before_provider_configuration(
    client_without_openai_key,
):
    response = await client_without_openai_key.post(
        "/api/v1/chat",
        json={"message": 123},
    )

    assert response.status_code == 422
    assert_error_response(response.json(), 422, "request validation failed")


@pytest.mark.asyncio
async def test_missing_openai_key_does_not_break_health_check(client_without_openai_key):
    health_response = await client_without_openai_key.get("/health")
    chat_response = await client_without_openai_key.post(
        "/api/v1/chat",
        json={"message": "hello"},
    )

    assert health_response.status_code == 200
    assert chat_response.status_code == 503
    assert_error_response(chat_response.json(), 503, "OPENAI_API_KEY")


@pytest.mark.asyncio
async def test_blank_openai_key_is_treated_as_missing(client_with_blank_openai_key):
    health_response = await client_with_blank_openai_key.get("/health")
    chat_response = await client_with_blank_openai_key.post(
        "/api/v1/chat",
        json={"message": "hello"},
    )

    assert health_response.status_code == 200
    assert chat_response.status_code == 503
    assert_error_response(chat_response.json(), 503, "OPENAI_API_KEY")


@pytest.mark.asyncio
async def test_provider_failure_returns_502_without_leaking_secret(
    client_with_invalid_openai_provider,
):
    response = await client_with_invalid_openai_provider.post(
        "/api/v1/chat",
        json={"message": "hello"},
    )

    response_text = response.text
    assert response.status_code == 502
    assert_error_response(response.json(), 502, "chat provider request failed")
    assert "test-secret-value" not in response_text
