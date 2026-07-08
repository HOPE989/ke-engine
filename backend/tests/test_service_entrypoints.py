import pytest
from httpx import ASGITransport, AsyncClient

from app.entrypoints.agent_api import app as agent_app
from app.entrypoints.document_api import app as document_app


@pytest.mark.asyncio
async def test_document_api_entrypoint_exposes_health_check():
    transport = ASGITransport(app=document_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ke-engine-document-api"}


@pytest.mark.asyncio
async def test_agent_api_entrypoint_exposes_chat_route_without_document_routes():
    transport = ASGITransport(app=agent_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        chat_response = await client.post("/api/v1/chat", json={"message": " "})
        document_response = await client.get("/api/v1/document/1")

    assert chat_response.status_code == 400
    assert document_response.status_code == 404
