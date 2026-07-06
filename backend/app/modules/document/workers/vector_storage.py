"""文档向量存储 Kafka worker。

worker 只负责消费 `document.embed_store.requested` 事件，并把结果转换为 Kafka commit
决策。业务上分两类结果：
- 终端结果：文档不存在、已 `VECTOR_STORED`、业务状态不是 `CHUNKED`、或向量存储成功。
  这些消息可以 commit。
- 可重试结果：锁被占用、OpenAI/Elasticsearch/数据库异常、ID 数量不一致、最终
  double-check 失败。这里不 commit，让 Kafka 后续重新投递。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.infrastructure.kafka import create_kafka_consumer
from app.modules.document.events import (
    DOCUMENT_EMBED_STORE_GROUP_ID,
    DOCUMENT_EMBED_STORE_REQUESTED_TOPIC,
    DocumentEmbedStoreRequested,
)
from app.modules.document.models import DocumentStatus
from app.modules.document.vector_storage import VectorStorageLockBusy, store_document_vectors

if TYPE_CHECKING:
    # 仅用于类型检查：Kafka/Celery worker host 都会导入本业务模块执行业务入口。
    # 这里避免运行时导入 host 模块，防止循环依赖和 worker 启动副作用。
    from app.workers.celery_worker import CeleryWorkerRuntime
    from app.workers.kafka_worker import DocumentVectorStorageContext, KafkaWorkerRuntime

logger = logging.getLogger(__name__)


async def run_document_vector_storage_consumer(runtime: KafkaWorkerRuntime) -> None:
    """启动长生命周期的向量存储 Kafka consumer。

    该 consumer 使用手动 commit。循环中只处理三件事：订阅 topic、忽略空 poll/consumer
    error、把有效 message 交给 `handle_document_vector_storage_message` 决定是否提交。
    """

    # 1. consumer group 独立于转换 worker，避免两个阶段互相抢消息。
    consumer = create_kafka_consumer(
        bootstrap_servers=runtime.settings.kafka_bootstrap_servers,
        group_id=DOCUMENT_EMBED_STORE_GROUP_ID,
    )
    # 2. topic 与事件类型保持一致，便于按业务阶段定位 Kafka 消息。
    await consumer.subscribe([DOCUMENT_EMBED_STORE_REQUESTED_TOPIC])
    logger.info(
        "document vector-storage kafka consumer subscribed topic=%s group_id=%s",
        DOCUMENT_EMBED_STORE_REQUESTED_TOPIC,
        DOCUMENT_EMBED_STORE_GROUP_ID,
    )
    try:
        while True:
            # 3. worker 常驻轮询；空 poll 不是错误，直接进入下一轮。
            message = await consumer.poll(timeout=1.0)
            if message is None:
                continue
            error = message.error()
            if error is not None:
                logger.warning("kafka consumer error: %s", error)
                continue
            await handle_document_vector_storage_message(
                message=message,
                consumer=consumer,
                runtime=runtime,
            )
    finally:
        await consumer.close()


async def handle_document_vector_storage_message(
    *,
    message: Any,
    consumer: Any,
    runtime: KafkaWorkerRuntime,
) -> None:
    """处理一条 Kafka message，并只提交终端结果。

    `run_document_vector_storage_with_runtime` 返回布尔值表达 commit 决策：`True` 表示该消息已经不需要
    重试，`False` 表示基础设施或业务处理仍可重试，必须保留 offset 未提交。
    """

    event = DocumentEmbedStoreRequested.from_json(message.value())
    should_commit = await run_document_vector_storage_with_runtime(
        doc_id=event.doc_id_int(),
        runtime=runtime,
    )
    if should_commit:
        await consumer.commit(message=message)


async def handle_document_vector_storage_event(
    *,
    doc_id: int,
    document_repository: Any,
    vector_store: Any,
    lock: Any,
) -> bool:
    """处理一个已解析的向量存储事件，并返回是否应 commit Kafka message。

    该函数接收已构造好的 repository/vector_store/lock，便于单元测试覆盖 commit 语义。
    文档状态预检查放在这里，确保非 `CHUNKED` 状态不会误触发 OpenAI 或 Elasticsearch。
    """

    # 1. 文档消失属于终端状态：消息无法再产生业务效果，应提交。
    document = await document_repository.get_document(doc_id)
    if document is None:
        return True
    # 2. 已完成状态保持幂等，不重复写向量。
    if document.status == DocumentStatus.VECTOR_STORED.value:
        return True
    # 3. 其他业务状态不是这个 worker 的可处理输入，也视为终端消息。
    if document.status != DocumentStatus.CHUNKED.value:
        return True

    try:
        # 4. 只有 CHUNKED 文档才进入长事务向量存储流程。
        await store_document_vectors(
            doc_id=doc_id,
            document_repository=document_repository,
            vector_store=vector_store,
            lock=lock,
        )
    except VectorStorageLockBusy:
        # 锁被占用说明另一个 worker 正在处理，保留消息未提交等待重试。
        return False
    except Exception:
        # OpenAI、ES、DB、ID mismatch、double-check 等失败都保持可重试。
        logger.exception("document vector storage failed", extra={"doc_id": doc_id})
        return False
    return True


async def run_document_vector_storage_with_runtime(
    *,
    doc_id: int,
    runtime: KafkaWorkerRuntime | CeleryWorkerRuntime,
) -> bool:
    """使用进程 runtime 为一个文档执行向量存储。

    1. DB repository、Redis client、embedding model 和 Elasticsearch adapter 都由 worker
       进程 runtime 在启动期创建；
    2. 这里仍然为每个文档创建独立 Redis lock，保持短生命周期上下文不进入 runtime；
    3. 返回值继续表达 Kafka commit 决策，Celery 调用方只复用业务结果而不触碰 offset。
    """

    from app.infrastructure.redis_lock import document_embed_store_lock

    vector_context = _get_vector_storage_context(runtime)
    document = await vector_context.repository.get_document(doc_id)
    if document is None:
        return True
    if document.status == DocumentStatus.VECTOR_STORED.value:
        return True
    if document.status != DocumentStatus.CHUNKED.value:
        return True

    lock = document_embed_store_lock(
        redis_client=vector_context.redis_client,
        doc_id=doc_id,
        expire_seconds=vector_context.lock_expire_seconds,
    )
    return await handle_document_vector_storage_event(
        doc_id=doc_id,
        document_repository=vector_context.repository,
        vector_store=vector_context.vector_store,
        lock=lock,
    )


def _get_vector_storage_context(
    runtime: KafkaWorkerRuntime | CeleryWorkerRuntime,
) -> DocumentVectorStorageContext:
    """从进程 runtime 中取出向量写入 context。

    Kafka worker 直接暴露 `vector_storage`；Celery worker 通过 `compensation.vector_storage`
    暴露自己的补偿上下文。这里保持分派逻辑很薄，避免把 Kafka/Celery 差异藏进共享
    runtime 构造器。
    """

    if hasattr(runtime, "vector_storage"):
        return runtime.vector_storage
    return runtime.compensation.vector_storage
