"""Document conversion dispatchers."""

from __future__ import annotations

from typing import Any

from app.modules.document.events import (
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
    """Dispatch document embedding and vector-storage requests to Kafka."""

    def __init__(self, producer: Any) -> None:
        self._producer = producer

    async def dispatch(self, doc_id: int) -> None:
        event = DocumentEmbedStoreRequested.create(doc_id=doc_id)
        delivery = await self._producer.produce(
            topic=DOCUMENT_EMBED_STORE_REQUESTED_TOPIC,
            key=event.doc_id.encode(),
            value=event.to_json().encode(),
        )
        await self._producer.flush()
        await delivery
