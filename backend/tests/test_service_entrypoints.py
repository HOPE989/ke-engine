import pytest
from httpx import ASGITransport, AsyncClient

from app.entrypoints.document_api import app as document_app


@pytest.mark.asyncio
async def test_document_api_entrypoint_exposes_health_check():
    transport = ASGITransport(app=document_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ke-engine-document-api"}
