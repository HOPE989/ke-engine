"""将本地业务理解用例显式 upsert 到 Langfuse Dataset。"""

import sys

from app.core.config import Settings, create_settings
from app.domains.chat.graph.business_understanding.evaluation import (
    load_evaluation_cases,
)
from app.evaluation.business_understanding_langfuse import (
    DATASET_NAME,
    sync_dataset,
)
from app.infrastructure.langfuse import LangfuseResources, create_langfuse_resources


def upsert_dataset(
    settings: Settings,
    *,
    resources: LangfuseResources | None = None,
):
    """显式写入本地用例；不运行模型或 Experiment。"""

    active_resources = resources or create_langfuse_resources(settings)
    if active_resources is None:
        raise RuntimeError("Langfuse configuration is required for Dataset upsert")

    client = active_resources.client
    try:
        if not client.auth_check():
            raise RuntimeError("Langfuse authentication failed")
        cases = load_evaluation_cases()
        dataset = sync_dataset(client, cases)
        print(f"Upserted {len(cases)} items to {DATASET_NAME}")
        return dataset
    finally:
        client.shutdown()


def main() -> int:
    try:
        upsert_dataset(create_settings())
    except Exception as exc:
        print(f"Langfuse Dataset upsert failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
