"""Chat HTTP 与 SSE 公共契约。"""

from app.contracts.chat.http import (
    CompletionRequest,
    ConversationPage,
    ConversationSummary,
    MessagePage,
    MessageSummary,
)
from app.contracts.chat.stream import (
    CompletedPayload,
    ContentDeltaPayload,
    ErrorPayload,
    MetadataPayload,
)

__all__ = [
    "CompletedPayload",
    "CompletionRequest",
    "ContentDeltaPayload",
    "ConversationPage",
    "ConversationSummary",
    "ErrorPayload",
    "MessagePage",
    "MessageSummary",
    "MetadataPayload",
]
