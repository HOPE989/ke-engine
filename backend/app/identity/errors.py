"""请求身份访问异常。"""

from fastapi import HTTPException


class MissingPrincipalError(HTTPException):
    """当前 HTTP 请求未经过身份恢复。"""

    def __init__(self) -> None:
        super().__init__(status_code=401, detail="Authentication required")
