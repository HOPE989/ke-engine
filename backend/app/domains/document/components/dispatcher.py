"""文档模块 Kafka dispatcher。

Dispatcher 封装 topic/key/value/flush 细节，workflow 只需要调用 `dispatch(doc_id)`。
所有 dispatcher 都等待 producer flush 和 delivery future，确保 API 或上游 workflow 在返回
“派发成功”前已经拿到 Kafka 客户端确认。
"""

from __future__ import annotations

from typing import Any

from app.contracts.document.events import (
    DOCUMENT_CONVERT_REQUESTED_TOPIC,
    DOCUMENT_EMBED_STORE_REQUESTED_TOPIC,
    DocumentConvertRequested,
    DocumentEmbedStoreRequested,
)


class KafkaDocumentConversionDispatcher:
    """Dispatch document conversion requests to Kafka."""

    def __init__(self, producer: Any) -> None:
        self._producer = producer

    async def dispatch(self, doc_id: int) -> None:
        event = DocumentConvertRequested.create(doc_id=doc_id)
        delivery = await self._producer.produce(
            topic=DOCUMENT_CONVERT_REQUESTED_TOPIC,
            key=event.doc_id.encode(),
            value=event.to_json().encode(),
        )
        await self._producer.flush()
        await delivery


class KafkaDocumentEmbedStoreDispatcher:
    """派发文档 embedding/vector-storage 请求。

    消息 key 使用 `doc_id`，让同一文档的向量存储事件在 Kafka 分区内保持顺序。
    """

    def __init__(self, producer: Any) -> None:
        self._producer = producer

    async def dispatch(self, doc_id: int) -> None:
        """发布 `document.embed_store.requested` 事件并等待 Kafka delivery 完成。"""

        event = DocumentEmbedStoreRequested.create(doc_id=doc_id)
        delivery = await self._producer.produce(
            topic=DOCUMENT_EMBED_STORE_REQUESTED_TOPIC,
            key=event.doc_id.encode(),
            value=event.to_json().encode(),
        )
        # flush 确保 producer 缓冲被推送；delivery future 负责暴露 broker ack/错误。
        await self._producer.flush()
        await delivery
