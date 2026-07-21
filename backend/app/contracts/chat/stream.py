"""应用拥有的 Chat SSE payload 契约。"""

from typing import Literal

from pydantic import BaseModel

from app.contracts.chat.http import ResponseId


class MetadataPayload(BaseModel):
    conversation_id: ResponseId
    user_message_id: ResponseId


class ContentDeltaPayload(BaseModel):
    content: str


class CompletedPayload(BaseModel):
    assistant_message_id: ResponseId
    finish_reason: Literal["stop", "interrupt"] = "stop"


class ErrorPayload(BaseModel):
    code: str
    message: str
    retryable: bool
