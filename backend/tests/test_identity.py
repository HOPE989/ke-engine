from dataclasses import FrozenInstanceError

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.requests import Request


def test_principal_is_immutable():
    from app.identity import Principal

    principal = Principal(user_id="user-001", tenant_id="tenant-001")

    with pytest.raises(FrozenInstanceError):
        principal.user_id = "other-user"


@pytest.mark.parametrize(
    ("headers", "expected_user_id", "expected_tenant_id"),
    [
        ({}, "dev-user-001", "dev-tenant-001"),
        (
            {
                "X-Mock-User-Id": "user-002",
                "X-Mock-Tenant-Id": "tenant-002",
            },
            "user-002",
            "tenant-002",
        ),
        ({"X-Mock-User-Id": "user-003"}, "user-003", "dev-tenant-001"),
    ],
)
def test_mock_identity_provider_uses_defaults_and_independent_header_overrides(
    headers,
    expected_user_id,
    expected_tenant_id,
):
    from app.identity import MockIdentityProvider

    principal = MockIdentityProvider().authenticate(Headers(headers))

    assert principal.user_id == expected_user_id
    assert principal.tenant_id == expected_tenant_id


class RecordingIdentityProvider:
    def __init__(self):
        self.calls = []

    def authenticate(self, headers):
        from app.identity import Principal

        self.calls.append(headers)
        return Principal(user_id="request-user", tenant_id="request-tenant")


async def _empty_receive():
    return {"type": "http.disconnect"}


@pytest.mark.asyncio
async def test_identity_middleware_sets_principal_before_calling_http_app():
    from app.identity import IdentityMiddleware

    provider = RecordingIdentityProvider()
    captured = {}

    async def downstream(scope, receive, send):
        captured["principal"] = scope["state"]["principal"]

    middleware = IdentityMiddleware(downstream, provider=provider)
    scope = {"type": "http", "path": "/documents", "headers": []}

    await middleware(scope, _empty_receive, lambda message: None)

    assert captured["principal"].user_id == "request-user"
    assert captured["principal"].tenant_id == "request-tenant"
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_identity_middleware_bypasses_exact_public_path():
    from app.identity import IdentityMiddleware

    provider = RecordingIdentityProvider()
    captured = {}

    async def downstream(scope, receive, send):
        captured["scope"] = scope

    middleware = IdentityMiddleware(
        downstream,
        provider=provider,
        public_paths={"/health"},
    )
    scope = {"type": "http", "path": "/health", "headers": []}

    await middleware(scope, _empty_receive, lambda message: None)

    assert captured["scope"] is scope
    assert "state" not in scope
    assert provider.calls == []


@pytest.mark.asyncio
async def test_identity_middleware_passes_non_http_scope_through_unchanged():
    from app.identity import IdentityMiddleware

    provider = RecordingIdentityProvider()
    captured = {}

    async def downstream(scope, receive, send):
        captured["scope"] = scope

    middleware = IdentityMiddleware(downstream, provider=provider)
    scope = {"type": "lifespan", "state": {"existing": "value"}}

    await middleware(scope, _empty_receive, lambda message: None)

    assert captured["scope"] is scope
    assert scope == {"type": "lifespan", "state": {"existing": "value"}}
    assert provider.calls == []


@pytest.mark.asyncio
async def test_identity_middleware_does_not_wrap_streaming_response():
    from app.identity import IdentityMiddleware

    provider = RecordingIdentityProvider()
    sent_messages = []

    async def downstream(scope, receive, send):
        principal = scope["state"]["principal"]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send(
            {
                "type": "http.response.body",
                "body": principal.user_id.encode(),
                "more_body": True,
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"-done",
                "more_body": False,
            }
        )

    async def send(message):
        sent_messages.append(message)

    middleware = IdentityMiddleware(downstream, provider=provider)
    scope = {"type": "http", "path": "/stream", "headers": []}

    await middleware(scope, _empty_receive, send)

    assert len(provider.calls) == 1
    assert sent_messages == [
        {"type": "http.response.start", "status": 200, "headers": []},
        {
            "type": "http.response.body",
            "body": b"request-user",
            "more_body": True,
        },
        {"type": "http.response.body", "body": b"-done", "more_body": False},
    ]


def test_current_principal_dependency_returns_same_instance():
    from app.identity import Principal, get_current_principal

    principal = Principal(user_id="user-001", tenant_id="tenant-001")
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/documents",
            "headers": [],
            "state": {"principal": principal},
        }
    )

    assert get_current_principal(request) is principal


def test_current_principal_dependency_returns_401_when_identity_is_missing():
    from app.identity import get_current_principal

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/documents",
            "headers": [],
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        get_current_principal(request)

    assert exc_info.value.status_code == 401
