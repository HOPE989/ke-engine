"""Document vector-storage workflow."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
from typing import Any

logger = logging.getLogger(__name__)

VECTOR_STORAGE_BATCH_SIZE = 100


class VectorStorageLockBusy(Exception):
    """Raised when another worker holds the document vector-storage lock."""


class VectorStorageIncomplete(Exception):
    """Raised when final pending-segment double-check still finds work."""


async def run_with_document_vector_storage_lock(
    *,
    lock: Any,
    operation: Callable[[], Awaitable[Any]],
) -> Any:
    """Run one vector-storage operation while holding the document lock."""

    acquired = lock.acquire(blocking=False)
    if not acquired:
        raise VectorStorageLockBusy()

    try:
        return await operation()
    finally:
        lock.release()


async def store_document_vectors(
    *,
    doc_id: int,
    document_repository: Any,
    vector_store: Any,
    lock: Any,
) -> None:
    """Embed and store all pending embeddable segments for one document."""

    async def operation() -> None:
        returned_ids: list[str] = []
        await vector_store.delete_by_doc_id(doc_id)
        try:
            async with document_repository.session() as session:
                async with session.begin():
                    while True:
                        segments = await document_repository.list_pending_embeddable_segments(
                            session=session,
                            doc_id=doc_id,
                            limit=VECTOR_STORAGE_BATCH_SIZE,
                        )
                        if not segments:
                            break

                        vector_ids = await vector_store.add_segments(segments)
                        returned_ids.extend(vector_ids)
                        await document_repository.mark_segments_vector_stored(
                            session=session,
                            segment_embedding_ids={
                                segment.id: vector_id
                                for segment, vector_id in zip(segments, vector_ids, strict=True)
                            },
                        )

                    remaining = await document_repository.count_pending_embeddable_segments(
                        session=session,
                        doc_id=doc_id,
                    )
                    if remaining:
                        raise VectorStorageIncomplete()

                    await document_repository.mark_document_vector_stored(
                        session=session,
                        doc_id=doc_id,
                    )
        except Exception as exc:
            await _cleanup_failed_attempt(
                vector_store=vector_store,
                doc_id=doc_id,
                returned_ids=[*returned_ids, *getattr(exc, "returned_ids", [])],
            )
            raise

    await run_with_document_vector_storage_lock(lock=lock, operation=operation)


async def _cleanup_failed_attempt(
    *,
    vector_store: Any,
    doc_id: int,
    returned_ids: list[str],
) -> None:
    if returned_ids:
        try:
            await vector_store.delete_by_ids(returned_ids)
        except Exception:
            logger.exception("failed to delete returned vector documents", extra={"doc_id": doc_id})
    try:
        await vector_store.delete_by_doc_id(doc_id)
    except Exception:
        logger.exception("failed to delete vector documents by docId", extra={"doc_id": doc_id})
