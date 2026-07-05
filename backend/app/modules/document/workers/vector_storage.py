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
    """启动长生命周期的向量存储 Kafka consumer。

    该 consumer 使用手动 commit。循环中只处理三件事：订阅 topic、忽略空 poll/consumer
    error、把有效 message 交给 `handle_document_vector_storage_message` 决定是否提交。
    """

    settings = get_settings()
    # 1. consumer group 独立于转换 worker，避免两个阶段互相抢消息。
    consumer = create_kafka_consumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
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
            await handle_document_vector_storage_message(message=message, consumer=consumer)
    finally:
        await consumer.close()


async def handle_document_vector_storage_message(*, message: Any, consumer: Any) -> None:
    """处理一条 Kafka message，并只提交终端结果。

    `run_document_vector_storage` 返回布尔值表达 commit 决策：`True` 表示该消息已经不需要
    重试，`False` 表示基础设施或业务处理仍可重试，必须保留 offset 未提交。
    """

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


async def run_document_vector_storage(doc_id: int) -> bool:
    """为一条向量存储事件创建运行时资源并执行处理。

    资源创建分阶段进行：先打开数据库读取文档状态，只有确认为 `CHUNKED` 后才创建 Redis
    lock、embedding model 和 Elasticsearch store。这样缺失文档、已完成文档或非法业务状态
    不会因为外部基础设施配置问题而阻塞 Kafka commit。
    """

    from app.db.session import close_engine, get_session_factory, init_engine
    from app.infrastructure.redis_lock import create_redis_client, document_embed_store_lock
    from app.modules.document.repository import DocumentRepository
    from app.modules.document.vector_store import (
        ElasticsearchVectorStoreAdapter,
        create_elasticsearch_store,
        create_embedding_model,
    )

    settings = get_settings()
    # 1. 先初始化数据库，因为文档状态决定是否需要后续 Redis/OpenAI/ES 资源。
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

        # 2. 只有 CHUNKED 文档才需要获取锁和创建外部服务 adapter。
        redis_client = create_redis_client(settings.redis_url)
        try:
            lock = document_embed_store_lock(
                redis_client=redis_client,
                doc_id=doc_id,
                expire_seconds=settings.document_convert_lock_expire_seconds,
            )
            # 3. 模型和 ES store 在 worker 侧构造，workflow 只接收抽象 adapter。
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
        # 4. 每条消息独立打开和关闭 DB engine，沿用现有 conversion worker 的资源模型。
        await close_engine()
