import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import register_exception_handlers
from app.services.agent_api.chat_router import router


def assert_error_response(payload: dict, status_code: int, message_part: str) -> None:
    assert payload["code"] == status_code
    assert message_part in payload["message"]
    assert payload["data"] is None


def create_chat_router_test_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/chat")
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["", "   "])
async def test_chat_router_rejects_blank_message(message):
    app = create_chat_router_test_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/chat", json={"message": message})

    assert response.status_code == 400
    assert_error_response(response.json(), 400, "message")


@pytest.mark.asyncio
async def test_chat_router_rejects_missing_message():
    app = create_chat_router_test_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/chat", json={})

    assert response.status_code == 422
    assert_error_response(response.json(), 422, "request validation failed")


@pytest.mark.asyncio
async def test_chat_router_rejects_non_string_message():
    app = create_chat_router_test_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/chat", json={"message": 123})

    assert response.status_code == 422
    assert_error_response(response.json(), 422, "request validation failed")
