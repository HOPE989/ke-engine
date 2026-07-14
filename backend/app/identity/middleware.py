"""请求身份恢复 Middleware。"""

from collections.abc import Collection

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from app.identity.provider import IdentityProvider


class IdentityMiddleware:
    """在受保护 HTTP 请求进入路由前写入请求身份。"""

    def __init__(
        self,
        app: ASGIApp,
        *,
        provider: IdentityProvider,
        public_paths: Collection[str] = (),
    ) -> None:
        self.app = app
        self.provider = provider
        self.public_paths = frozenset(public_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.public_paths:
            await self.app(scope, receive, send)
            return

        scope.setdefault("state", {})["principal"] = self.provider.authenticate(
            Headers(scope=scope)
        )
        await self.app(scope, receive, send)
