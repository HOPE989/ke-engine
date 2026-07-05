"""Kafka worker process entrypoint."""

from __future__ import annotations

import asyncio

from app.core.logging import configure_logging
from app.modules.document.workers.conversion import run_document_conversion_consumer
from app.modules.document.workers.vector_storage import run_document_vector_storage_consumer


async def start_worker_consumers() -> None:
    """Start module-owned Kafka consumer runners."""

    async with asyncio.TaskGroup() as task_group:
        task_group.create_task(run_document_conversion_consumer())
        task_group.create_task(run_document_vector_storage_consumer())


async def main() -> None:
    configure_logging()
    await start_worker_consumers()


if __name__ == "__main__":
    asyncio.run(main())
