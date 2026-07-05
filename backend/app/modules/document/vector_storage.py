"""文档向量存储工作流。

本模块只负责编排一个已 `CHUNKED` 文档的向量化尝试：
- 通过 Redis 单文档锁保证同一文档不会被并发处理；
- 在进入事务前先清理该文档遗留的 Elasticsearch 向量；
- 在一个数据库事务中分页读取待处理 segment、写入向量、回填 `embedding_id`；
- 最后通过 pending segment double-check 决定是否推进文档到 `VECTOR_STORED`；
- 任意失败都会回滚数据库事务，并尽力清理本轮已写入的 Elasticsearch 向量。

这里不处理 Kafka commit、文档状态预检查、模型/ES client 创建。这些边界由 worker 和
vector-store adapter 负责，避免 workflow 同时承担过多基础设施职责。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
from typing import Any

logger = logging.getLogger(__name__)

VECTOR_STORAGE_BATCH_SIZE = 100


class VectorStorageLockBusy(Exception):
    """另一个 worker 已持有同一文档的向量存储锁。

    这是可重试状态：调用方不应把 Kafka 消息提交掉，让后续投递重新尝试。
    """


class VectorStorageIncomplete(Exception):
    """最终 double-check 仍发现待向量化 segment。

    该异常表示本次尝试没有完整覆盖所有待处理行，数据库事务需要回滚，Kafka 消息也应保持
    未提交以便重试。
    """


async def run_with_document_vector_storage_lock(
    *,
    lock: Any,
    operation: Callable[[], Awaitable[Any]],
) -> Any:
    """在单文档 Redis 锁内执行向量存储操作。

    锁只用于防止同一 `doc_id` 被多个 worker 同时处理。它不替代数据库事务，也不承担
    失败恢复；失败恢复由 `store_document_vectors` 的补偿逻辑处理。
    """

    acquired = lock.acquire(blocking=False)
    if not acquired:
        raise VectorStorageLockBusy()

    try:
        # 锁获取成功后才进入实际业务，避免 busy lock 情况下打开数据库事务或清理 ES。
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
    """将一个文档所有待处理 segment 写入 Elasticsearch 向量索引。

    处理顺序严格遵守 OpenSpec 设计：
    1. 持有单文档锁；
    2. 处理前先按 `metadata.docId` 删除残留向量，清理上次失败的外部副作用；
    3. 打开一个长数据库事务；
    4. 每轮都查询固定第一页待处理 segment，避免 offset pagination 因状态变更跳行；
    5. 将 LangChain/Elasticsearch 返回的 ID 按原顺序回填到 `knowledge_segment.embedding_id`；
    6. 最终 double-check 无剩余待处理 segment 后，才推进文档到 `VECTOR_STORED`；
    7. 任意失败都回滚数据库事务，并尽力删除本轮返回的向量 ID 及该 docId 下的向量。
    """

    async def operation() -> None:
        returned_ids: list[str] = []
        # 1. 清理上次失败可能留下的孤儿向量。此操作在数据库事务外执行。
        await vector_store.delete_by_doc_id(doc_id)
        try:
            async with document_repository.session() as session:
                async with session.begin():
                    while True:
                        # 2. 固定查询第一页。成功处理一批后状态会变更，下一轮再查第一页即可。
                        segments = await document_repository.list_pending_embeddable_segments(
                            session=session,
                            doc_id=doc_id,
                            limit=VECTOR_STORAGE_BATCH_SIZE,
                        )
                        if not segments:
                            break

                        # 3. 外部向量写入发生在同一个数据库事务期间，满足数据库侧全有或全无。
                        vector_ids = await vector_store.add_segments(segments)
                        returned_ids.extend(vector_ids)
                        # 4. 只在 Elasticsearch 返回 ID 后回填 DB，保持 segment 与向量 ID 对齐。
                        await document_repository.mark_segments_vector_stored(
                            session=session,
                            segment_embedding_ids={
                                segment.id: vector_id
                                for segment, vector_id in zip(segments, vector_ids, strict=True)
                            },
                        )

                    # 5. 最后一轮 double-check 是文档完成的唯一 gate。
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
            # 数据库回滚无法撤销 Elasticsearch 写入，所以失败时必须做补偿清理。
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
    """清理失败尝试产生的 Elasticsearch 外部副作用。

    优先按本轮已知的返回 ID 精确删除；随后再按 `metadata.docId` 兜底删除。清理失败只记录
    日志，不吞掉原始业务异常，调用方仍会看到导致重试的根因。
    """

    if returned_ids:
        try:
            await vector_store.delete_by_ids(returned_ids)
        except Exception:
            logger.exception("failed to delete returned vector documents", extra={"doc_id": doc_id})
    try:
        await vector_store.delete_by_doc_id(doc_id)
    except Exception:
        logger.exception("failed to delete vector documents by docId", extra={"doc_id": doc_id})
