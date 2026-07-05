"""文档模块拥有的 Kafka 事件 payload 定义。

事件类只负责稳定序列化/反序列化，不触碰 Kafka producer/consumer。这样 API、workflow 和
worker 可以共享同一份 payload contract，避免 topic 字符串和字段格式散落在多个模块。
"""

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
    """请求转换一个已上传文档的事件。

    `doc_id` 使用字符串序列化，避免 JavaScript/JSON 消费端对 64-bit Snowflake ID 产生
    精度损失。
    """

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
    """请求对一个已切分文档执行 embedding 和向量存储的事件。

    该事件的正常来源是 chunking 成功后的自动派发，也可以由手动
    `POST /api/v1/document/{doc_id}/embed-store` 触发。payload 不携带 segment 明细，
    worker 会在处理时从数据库读取最新的 `CHUNKED` 文档状态和待处理 segment。
    """

    event_id: str
    event_type: str
    doc_id: str
    occurred_at: str

    @classmethod
    def create(cls, *, doc_id: int) -> "DocumentEmbedStoreRequested":
        """基于文档 ID 生成新的向量存储请求事件。"""

        return cls(
            event_id=str(uuid4()),
            event_type=DOCUMENT_EMBED_STORE_REQUESTED,
            doc_id=str(doc_id),
            occurred_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> "DocumentEmbedStoreRequested":
        """从 Kafka message payload 恢复事件并校验类型和 doc_id 格式。"""

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
        """序列化为 Kafka value 使用的紧凑 JSON 字符串。"""

        return json.dumps(asdict(self), separators=(",", ":"))

    def doc_id_int(self) -> int:
        """把字符串形式的 doc_id 转回后端内部使用的整数。"""

        return int(self.doc_id)
