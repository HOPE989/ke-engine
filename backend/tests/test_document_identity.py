from typing import Annotated

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.services.document_api.app import create_app


@pytest.mark.asyncio
async def test_document_api_registers_mock_identity_chain_and_keeps_health_public(
    monkeypatch,
):
    from app.identity import MockIdentityProvider, Principal, get_current_principal

    authenticate_calls = []
    original_authenticate = MockIdentityProvider.authenticate

    def recording_authenticate(self, headers):
        authenticate_calls.append(headers)
        return original_authenticate(self, headers)

    monkeypatch.setattr(MockIdentityProvider, "authenticate", recording_authenticate)
    application = create_app()

    @application.get("/_identity-probe")
    async def identity_probe(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> dict[str, str]:
        return {
            "user_id": principal.user_id,
            "tenant_id": principal.tenant_id,
        }

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health_response = await client.get("/health")
        assert health_response.status_code == 200
        assert authenticate_calls == []

        identity_response = await client.get(
            "/_identity-probe",
            headers={
                "X-Mock-User-Id": "document-user",
                "X-Mock-Tenant-Id": "document-tenant",
            },
        )

    assert identity_response.status_code == 200
    assert identity_response.json() == {
        "user_id": "document-user",
        "tenant_id": "document-tenant",
    }
    assert len(authenticate_calls) == 1
