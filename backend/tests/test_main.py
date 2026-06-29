import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_check_returns_ok():
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ke-engine"}


@pytest.mark.asyncio
async def test_api_v1_module_routes_are_mounted():
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/v1/users/")).status_code == 200
        assert (await client.get("/api/v1/auth/health")).status_code == 200
        assert (await client.get("/api/v1/orders/")).status_code == 200
