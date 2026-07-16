"""Chat HTTP 契约。"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

ResponseId = Annotated[str, BeforeValidator(str)]


class CompletionRequest(BaseModel):
    """服务端模型驱动的 completion 输入。"""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str | None = Field(default=None, pattern=r"^[0-9]+$")
    content: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("content must not be blank")
        return normalized


class ConversationSummary(BaseModel):
    """会话列表中的稳定字段。"""

    id: ResponseId
    title: str
    status: str
    created_at: datetime
    updated_at: datetime


class ConversationPage(BaseModel):
    """按 cursor 分页的会话结果。"""

    items: list[ConversationSummary]
    next_cursor: str | None


class MessageSummary(BaseModel):
    """消息历史中的稳定字段。"""

    id: ResponseId
    conversation_id: ResponseId
    parent_message_id: ResponseId | None
    role: str
    content: str
    created_at: datetime


class MessagePage(BaseModel):
    """按 cursor 分页的消息结果。"""

    items: list[MessageSummary]
    next_cursor: str | None
