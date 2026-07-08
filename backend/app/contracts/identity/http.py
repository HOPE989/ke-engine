"""Identity HTTP 契约类型。"""

from pydantic import BaseModel


class IdentityPrincipal(BaseModel):
    """内部服务调用中的身份主体。"""

    subject: str
