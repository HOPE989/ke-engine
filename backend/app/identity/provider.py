"""身份来源的公共边界。"""

from collections.abc import Mapping
from typing import Protocol

from app.identity.principal import Principal


class IdentityProvider(Protocol):
    """根据请求 Header 恢复 Principal。"""

    def authenticate(self, headers: Mapping[str, str]) -> Principal: ...
