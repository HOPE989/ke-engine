"""公共请求身份能力。"""

from app.identity.dependencies import get_current_principal
from app.identity.middleware import IdentityMiddleware
from app.identity.principal import Principal
from app.identity.provider import IdentityProvider
from app.identity.providers.mock import MockIdentityProvider

__all__ = [
    "IdentityMiddleware",
    "IdentityProvider",
    "MockIdentityProvider",
    "Principal",
    "get_current_principal",
]
