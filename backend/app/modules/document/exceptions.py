from fastapi import status

from app.core.exceptions import AppException


class DocumentStateConflictError(AppException):
    def __init__(self, message: str = "document state conflict") -> None:
        super().__init__(message=message, status_code=status.HTTP_409_CONFLICT)
