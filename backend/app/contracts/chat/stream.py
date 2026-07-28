"""应用拥有的 Chat SSE payload 契约。"""

from typing import Literal

from pydantic import BaseModel, Field

from app.contracts.chat.http import ResponseId

CompletionFinishReason = Literal["stop", "interrupt"]


class MetadataPayload(BaseModel):
    conversation_id: ResponseId
    user_message_id: ResponseId


class ContentDeltaPayload(BaseModel):
    content: str


class TraceStepPayload(BaseModel):
    node: str
    status: Literal["started", "completed"]


class RagEvidenceItemPayload(BaseModel):
    source_type: Literal["DOCUMENT"]
    citation_id: str
    content: str
    doc_id: str
    chunk_id: str
    file_name: str | None = None
    url: str | None = None
    rerank_score: float | None = None


class RagEvidencePayload(BaseModel):
    standalone_query: str
    selected_retrievers: tuple[str, ...]
    evidence_items: tuple[RagEvidenceItemPayload, ...] = Field(default=())


class CompletedPayload(BaseModel):
    assistant_message_id: ResponseId
    finish_reason: CompletionFinishReason = "stop"


class ErrorPayload(BaseModel):
    code: str
    message: str
    retryable: bool
