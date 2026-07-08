"""Celery compensation task for stale document vector storage."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from celery import shared_task

from app.domains.document.workers.vectorization_consumer import run_document_vector_storage_with_runtime

if TYPE_CHECKING:
    # 仅用于类型检查：Celery worker host 会导入 task 完成注册和生命周期装配。
    # 这里避免运行时导入 host 模块，防止循环依赖和 Celery 启动副作用。
    from app.entrypoints.celery_worker import CeleryWorkerRuntime

logger = logging.getLogger(__name__)

DOCUMENT_VECTOR_STORAGE_COMPENSATION_TASK_NAME = (
    "document.vector_storage.compensate_stale_chunked"
)
DOCUMENT_VECTOR_STORAGE_COMPENSATION_INTERVAL_SECONDS = 300.0
STALE_CHUNKED_THRESHOLD = timedelta(minutes=5)


@shared_task(name=DOCUMENT_VECTOR_STORAGE_COMPENSATION_TASK_NAME)
def compensate_stale_chunked_document_vectors_task() -> dict[str, int]:
    """同步 Celery task 包装器，把异步补偿流程提交到子进程长期 loop。

    这里不创建 event loop，也不创建 runtime 资源；它只读取 worker host 在子进程启动阶段
    保存的 `CeleryWorkerRuntime`。
    """

    from app.entrypoints.celery_worker import (
        get_celery_worker_runtime,
        submit_celery_runtime_coroutine,
    )

    return submit_celery_runtime_coroutine(
        compensate_stale_chunked_document_vectors(runtime=get_celery_worker_runtime())
    )


async def compensate_stale_chunked_document_vectors(
    *,
    runtime: CeleryWorkerRuntime,
) -> dict[str, int]:
    """扫描 stale `CHUNKED` 文档并复用 runtime 注入的向量存储流程。

    1. 候选扫描使用 `runtime.compensation` 暴露的 repository 创建短生命周期 DB session；
    2. 每个候选文档直接调用向量存储业务入口，不发布 Kafka 事件；
    3. 单个文档失败只计入 failed，后续候选仍继续处理。
    """

    doc_ids = await _scan_stale_chunked_document_ids(runtime=runtime)
    summary = {"total": len(doc_ids), "succeeded": 0, "failed": 0}

    for doc_id in doc_ids:
        try:
            stored = await run_document_vector_storage_with_runtime(
                doc_id=doc_id,
                runtime=runtime,
            )
        except Exception:
            logger.exception(
                "document vector-storage compensation failed unexpectedly",
                extra={"doc_id": doc_id},
            )
            summary["failed"] += 1
            continue

        if stored:
            summary["succeeded"] += 1
        else:
            logger.info(
                "document vector-storage compensation left document retryable",
                extra={"doc_id": doc_id},
            )
            summary["failed"] += 1

    logger.info("document vector-storage compensation finished", extra=summary)
    return summary


async def _scan_stale_chunked_document_ids(
    *,
    runtime: CeleryWorkerRuntime,
) -> list[int]:
    """通过 Celery compensation context 的 repository 扫描需要补偿的文档 ID。

    这里不拥有 DB engine 生命周期；repository 内部仍会为本次扫描创建短生命周期 session。
    """

    return await runtime.compensation.repository.list_stale_chunked_document_ids(
        older_than=STALE_CHUNKED_THRESHOLD
    )
