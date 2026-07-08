"""Document 事件契约。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import uuid4

DOCUMENT_CONVERT_REQUESTED = "document.convert.requested"
DOCUMENT_CONVERT_REQUESTED_TOPIC = DOCUMENT_CONVERT_REQUESTED
DOCUMENT_CONVERT_GROUP_ID = "ke-engine-document-converter"
DOCUMENT_EMBED_STORE_REQUESTED = "document.embed_store.requested"
DOCUMENT_EMBED_STORE_REQUESTED_TOPIC = DOCUMENT_EMBED_STORE_REQUESTED
DOCUMENT_EMBED_STORE_GROUP_ID = "ke-engine-document-embed-store"


@dataclass(frozen=True, slots=True)
class DocumentConvertRequested:
    """请求转换一个已上传文档的事件。"""

    event_id: str
    event_type: str
    doc_id: str
    occurred_at: str

    @classmethod
    def create(cls, *, doc_id: int) -> "DocumentConvertRequested":
        return cls(
            event_id=str(uuid4()),
            event_type=DOCUMENT_CONVERT_REQUESTED,
            doc_id=str(doc_id),
            occurred_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> "DocumentConvertRequested":
        data = json.loads(payload)
        event = cls(
            event_id=str(data["event_id"]),
            event_type=str(data["event_type"]),
            doc_id=str(data["doc_id"]),
            occurred_at=str(data["occurred_at"]),
        )
        if event.event_type != DOCUMENT_CONVERT_REQUESTED:
            raise ValueError(f"unsupported event_type: {event.event_type}")
        int(event.doc_id)
        return event

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    def doc_id_int(self) -> int:
        return int(self.doc_id)


@dataclass(frozen=True, slots=True)
class DocumentEmbedStoreRequested:
    """请求对一个已切分文档执行 embedding 和向量存储的事件。"""

    event_id: str
    event_type: str
    doc_id: str
    occurred_at: str

    @classmethod
    def create(cls, *, doc_id: int) -> "DocumentEmbedStoreRequested":
        return cls(
            event_id=str(uuid4()),
            event_type=DOCUMENT_EMBED_STORE_REQUESTED,
            doc_id=str(doc_id),
            occurred_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> "DocumentEmbedStoreRequested":
        data = json.loads(payload)
        event = cls(
            event_id=str(data["event_id"]),
            event_type=str(data["event_type"]),
            doc_id=str(data["doc_id"]),
            occurred_at=str(data["occurred_at"]),
        )
        if event.event_type != DOCUMENT_EMBED_STORE_REQUESTED:
            raise ValueError(f"unsupported event_type: {event.event_type}")
        int(event.doc_id)
        return event

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    def doc_id_int(self) -> int:
        return int(self.doc_id)
