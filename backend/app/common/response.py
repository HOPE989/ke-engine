from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: T | None = None


def success_response(data: T | None = None, message: str = "success") -> APIResponse[T]:
    return APIResponse(data=data, message=message)


def error_response(message: str, code: int) -> APIResponse[None]:
    return APIResponse(code=code, message=message, data=None)
