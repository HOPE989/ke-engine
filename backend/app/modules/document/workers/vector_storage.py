"""Document vector-storage Kafka worker."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.infrastructure.kafka import create_kafka_consumer
from app.modules.document.events import (
    DOCUMENT_EMBED_STORE_GROUP_ID,
    DOCUMENT_EMBED_STORE_REQUESTED_TOPIC,
    DocumentEmbedStoreRequested,
)
from app.modules.document.models import DocumentStatus
from app.modules.document.vector_storage import VectorStorageLockBusy, store_document_vectors

logger = logging.getLogger(__name__)


async def run_document_vector_storage_consumer() -> None:
    """Run the long-lived document vector-storage Kafka consumer loop."""

    settings = get_settings()
    consumer = create_kafka_consumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=DOCUMENT_EMBED_STORE_GROUP_ID,
    )
    await consumer.subscribe([DOCUMENT_EMBED_STORE_REQUESTED_TOPIC])
    logger.info(
        "document vector-storage kafka consumer subscribed topic=%s group_id=%s",
        DOCUMENT_EMBED_STORE_REQUESTED_TOPIC,
        DOCUMENT_EMBED_STORE_GROUP_ID,
    )
    try:
        while True:
            message = await consumer.poll(timeout=1.0)
            if message is None:
                continue
            error = message.error()
            if error is not None:
                logger.warning("kafka consumer error: %s", error)
                continue
            await handle_document_vector_storage_message(message=message, consumer=consumer)
    finally:
        await consumer.close()


async def handle_document_vector_storage_message(*, message: Any, consumer: Any) -> None:
    """Handle one vector-storage Kafka message and commit terminal outcomes."""

    event = DocumentEmbedStoreRequested.from_json(message.value())
    should_commit = await run_document_vector_storage(doc_id=event.doc_id_int())
    if should_commit:
        await consumer.commit(message=message)


async def handle_document_vector_storage_event(
    *,
    doc_id: int,
    document_repository: Any,
    vector_store: Any,
    lock: Any,
) -> bool:
    """Return whether the Kafka message reached a terminal outcome."""

    document = await document_repository.get_document(doc_id)
    if document is None:
        return True
    if document.status == DocumentStatus.VECTOR_STORED.value:
        return True
    if document.status != DocumentStatus.CHUNKED.value:
        return True

    try:
        await store_document_vectors(
            doc_id=doc_id,
            document_repository=document_repository,
            vector_store=vector_store,
            lock=lock,
        )
    except VectorStorageLockBusy:
        return False
    except Exception:
        logger.exception("document vector storage failed", extra={"doc_id": doc_id})
        return False
    return True


async def run_document_vector_storage(doc_id: int) -> bool:
    """Create per-message resources and process one vector-storage event."""

    from app.db.session import close_engine, get_session_factory, init_engine
    from app.infrastructure.redis_lock import create_redis_client, document_embed_store_lock
    from app.modules.document.repository import DocumentRepository
    from app.modules.document.vector_store import (
        ElasticsearchVectorStoreAdapter,
        create_elasticsearch_store,
        create_embedding_model,
    )

    settings = get_settings()
    await init_engine(settings.database_url)
    try:
        repository = DocumentRepository(get_session_factory())
        document = await repository.get_document(doc_id)
        if document is None:
            return True
        if document.status == DocumentStatus.VECTOR_STORED.value:
            return True
        if document.status != DocumentStatus.CHUNKED.value:
            return True

        redis_client = create_redis_client(settings.redis_url)
        try:
            lock = document_embed_store_lock(
                redis_client=redis_client,
                doc_id=doc_id,
                expire_seconds=settings.document_convert_lock_expire_seconds,
            )
            embedding_model = create_embedding_model(settings)
            store = create_elasticsearch_store(settings=settings, embedding_model=embedding_model)
            return await handle_document_vector_storage_event(
                doc_id=doc_id,
                document_repository=repository,
                vector_store=ElasticsearchVectorStoreAdapter(
                    store=store,
                    client=getattr(store, "client", None),
                    index_name=settings.elasticsearch_index,
                ),
                lock=lock,
            )
        finally:
            redis_client.close()
    finally:
        await close_engine()
