"""请求级身份模型。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    """一次 HTTP 请求中已恢复的用户与租户身份。"""

    user_id: str
    tenant_id: str
