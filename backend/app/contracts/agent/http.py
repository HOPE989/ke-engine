"""Agent HTTP 契约类型。"""

from pydantic import BaseModel, StrictStr


class ChatRequest(BaseModel):
    message: StrictStr


class ChatResponse(BaseModel):
    answer: str
