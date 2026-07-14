"""本地联调使用的 Mock 身份提供器。"""

from collections.abc import Mapping

from app.identity.config import (
    DEFAULT_MOCK_TENANT_ID,
    DEFAULT_MOCK_USER_ID,
    MOCK_TENANT_ID_HEADER,
    MOCK_USER_ID_HEADER,
)
from app.identity.principal import Principal


class MockIdentityProvider:
    """使用固定开发身份和可选 Mock Header 恢复请求身份。"""

    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        return Principal(
            user_id=headers.get(MOCK_USER_ID_HEADER) or DEFAULT_MOCK_USER_ID,
            tenant_id=headers.get(MOCK_TENANT_ID_HEADER) or DEFAULT_MOCK_TENANT_ID,
        )
