"""Document conversion Kafka worker."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from app.infrastructure.kafka import create_kafka_consumer
from app.contracts.document.events import (
    DOCUMENT_CONVERT_GROUP_ID,
    DOCUMENT_CONVERT_REQUESTED_TOPIC,
    DocumentConvertRequested,
)

if TYPE_CHECKING:
    # 仅用于类型检查：Kafka worker host 会导入本业务模块注册 consumer handler。
    # 这里避免运行时导入 host 模块，防止形成 worker host <-> handler 的循环依赖。
    from app.entrypoints.document_worker import KafkaWorkerRuntime

logger = logging.getLogger("app.domains.document.workers.conversion_consumer")


async def run_document_conversion_consumer(runtime: KafkaWorkerRuntime) -> None:
    """启动长生命周期的文档转换 Kafka consumer。

    Kafka consumer 实例属于本消费循环；它只共享进程级 `KafkaWorkerRuntime` 里的基础设施
    资源，不和向量存储 consumer 共享 topic/group/offset 状态。
    """

    consumer = create_kafka_consumer(
        bootstrap_servers=runtime.settings.kafka_bootstrap_servers,
        group_id=DOCUMENT_CONVERT_GROUP_ID,
    )
    await consumer.subscribe([DOCUMENT_CONVERT_REQUESTED_TOPIC])
    logger.info(
        "document conversion kafka consumer subscribed topic=%s group_id=%s",
        DOCUMENT_CONVERT_REQUESTED_TOPIC,
        DOCUMENT_CONVERT_GROUP_ID,
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
            await handle_document_conversion_message(
                message=message,
                consumer=consumer,
                runtime=runtime,
            )
    finally:
        await consumer.close()


async def handle_document_conversion_message(
    *,
    message: Any,
    consumer: Any,
    runtime: KafkaWorkerRuntime,
) -> None:
    """处理并提交一条文档转换 Kafka message。

    转换成功才提交 offset；异常继续向外抛出，保持原有 Kafka 重试语义。
    """

    event = DocumentConvertRequested.from_json(message.value())
    doc_id = event.doc_id_int()
    started_at = time.perf_counter()
    logger.info("processing document conversion message doc_id=%s", doc_id)
    try:
        await run_document_conversion(doc_id=doc_id, runtime=runtime)
        await consumer.commit(message=message)
    except Exception:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.exception(
            "failed to handle document conversion message doc_id=%s elapsed_ms=%.2f",
            doc_id,
            elapsed_ms,
        )
        raise
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "committed document conversion message doc_id=%s elapsed_ms=%.2f",
        doc_id,
        elapsed_ms,
    )


async def run_document_conversion(*, doc_id: int, runtime: KafkaWorkerRuntime) -> None:
    """使用 Kafka 进程 runtime 执行一次文档转换。

    1. Redis client 和锁过期时间来自 `runtime.conversion` typed context；
    2. 每个文档仍只创建自己的 Redis lock，避免把短生命周期锁对象放入 runtime；
    3. 函数不负责打开或关闭 DB engine，数据库生命周期由 worker 进程 runtime 统一管理。
    """

    from app.infrastructure.redis import document_conversion_lock

    conversion_context = runtime.conversion
    lock = document_conversion_lock(
        redis_client=conversion_context.redis_client,
        doc_id=doc_id,
        expire_seconds=conversion_context.lock_expire_seconds,
    )
    if not lock.acquire(blocking=False):
        # 普通文档沿用历史语义：同 doc_id 锁忙时直接跳过并提交消息。
        # DATA_QUERY spreadsheet 处于 UPLOADED 时必须重试，否则可能永远不导入动态表。
        if await _is_retryable_data_query_conversion_lock_busy(doc_id=doc_id, runtime=runtime):
            from app.domains.document.shared.errors import DocumentConversionLockBusy

            raise DocumentConversionLockBusy()
        return
    try:
        await run_locked_document_conversion(doc_id=doc_id, runtime=runtime)
    finally:
        lock.release()


async def _is_retryable_data_query_conversion_lock_busy(
    *,
    doc_id: int,
    runtime: KafkaWorkerRuntime,
) -> bool:
    """判断文档锁忙时是否应让 Kafka 消息保持未提交。

    只有 DATA_QUERY spreadsheet 且仍处于 UPLOADED 时才需要重试。已经 STORED 或其他
    非 UPLOADED 状态的消息可以按终端消息处理，避免因为旧消息一直阻塞消费进度。
    """

    from app.domains.document.shared.file_types import DocumentFileType
    from app.domains.document.shared.models import DocumentStatus, KnowledgeBaseType

    repository = getattr(runtime.conversion, "repository", None)
    if repository is None:
        return False
    document = await repository.get_document(doc_id)
    if document is None:
        return False
    # 这里读取的是当前数据库状态，而不是 Kafka payload，避免旧消息误判。
    return (
        document.status == DocumentStatus.UPLOADED.value
        and getattr(document, "knowledge_base_type", None) == KnowledgeBaseType.DATA_QUERY.value
        and getattr(document, "file_type", None)
        in {DocumentFileType.EXCEL.value, DocumentFileType.CSV.value}
    )


async def run_locked_document_conversion(
    *,
    doc_id: int,
    runtime: KafkaWorkerRuntime,
) -> None:
    """在已持有文档锁时执行转换业务。

    这里是 Kafka message 的文档执行热路径，只消费 conversion context 暴露的长生命周期
    资源视图：repository 负责短生命周期 DB session，storage/MinerU/image_describer
    负责实际转换能力，converter_factory 负责按文件类型分发具体转换器。
    """

    from app.domains.document.services.conversion import convert_uploaded_document

    conversion_context = runtime.conversion
    await convert_uploaded_document(
        doc_id=doc_id,
        document_repository=conversion_context.repository,
        storage=conversion_context.storage,
        mineru_client=conversion_context.mineru_client,
        image_describer=conversion_context.image_describer,
        converter_factory=conversion_context.converter_factory,
    )
