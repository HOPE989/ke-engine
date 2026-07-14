"""FastAPI 当前身份依赖。"""

from fastapi import Request

from app.identity.errors import MissingPrincipalError
from app.identity.principal import Principal


def get_current_principal(request: Request) -> Principal:
    """返回 Middleware 恢复的同一个 Principal 实例。"""

    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise MissingPrincipalError()
    return principal
