"""RAG Query Rewrite 的 Langfuse Dataset Experiment 入口。"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from functools import partial
import sys
from typing import Any
from uuid import UUID, uuid5

from langfuse import Evaluation
from langfuse.api.commons.errors import NotFoundError

from app.core.config import Settings, create_settings
from app.domains.rag.graph import build_rag_graph
from app.domains.rag.graph.query_rewrite.evaluation import (
    QueryRewriteEvaluationCase,
    load_query_rewrite_evaluation_cases,
    score_query_rewrite_output,
)
from app.domains.rag.graph.query_rewrite.prompt import (
    QUERY_REWRITE_PROMPT_VERSION,
)
from app.infrastructure.langfuse import (
    LangfuseResources,
    create_langfuse_resources,
)
from app.infrastructure.llm import create_chat_model


DATASET_NAME = "ke-engine/rag-query-rewrite-v1"
DATASET_ITEM_NAMESPACE = UUID("90c7a3fb-7dd7-4a9f-a1f5-0d3a0ab2702e")


def dataset_item_id(case: QueryRewriteEvaluationCase) -> str:
    """为 fixture case 生成可跨重复上传稳定复用的 Dataset item ID。"""

    return uuid5(
        DATASET_ITEM_NAMESPACE,
        f"{DATASET_NAME}:{case.id}",
    ).hex


def dataset_item_payload(
    case: QueryRewriteEvaluationCase,
) -> dict[str, Any]:
    """映射 Dataset item，同时保留人工语义评审所需的信息。"""

    return {
        "id": dataset_item_id(case),
        "input": case.request.model_dump(mode="json"),
        "expected_output": {
            "expected_standalone_query": case.expected_standalone_query,
            "semantic_review": {
                "preserved_terms": list(case.expected_preserved_terms),
                "required_term_groups": [
                    list(group)
                    for group in case.expected_required_term_groups
                ],
                "excluded_terms": list(case.expected_excluded_terms),
            },
        },
        "metadata": {
            "case_id": case.id,
            "category": case.category,
        },
    }


def langfuse_evaluator(
    *,
    output: Mapping[str, Any],
    **_: Any,
) -> list[Evaluation]:
    """只记录客观输出契约；语义质量留给人工或校准后的 Judge。"""

    score = score_query_rewrite_output(output)
    hits, total = score.output_contract
    return [
        Evaluation(
            name="output_contract",
            value=hits / total,
            comment=f"{hits}/{total}",
            data_type="NUMERIC",
        )
    ]


async def run_query_rewrite_case(
    *,
    item: Any,
    graph: Any,
) -> dict[str, str]:
    """使用生产 RAG Graph 执行一个 Dataset item。"""

    result = await graph.ainvoke(dict(item.input))
    return {"standalone_query": result["standalone_query"]}


def sync_dataset(
    client: Any,
    cases: Sequence[QueryRewriteEvaluationCase],
) -> Any:
    """创建或复用固定 Dataset，并以稳定 ID 幂等写入本地样例。"""

    try:
        client.get_dataset(DATASET_NAME)
    except NotFoundError:
        client.create_dataset(
            name=DATASET_NAME,
            description=(
                "28 labeled RAG Query Rewrite semantic review cases"
            ),
            metadata={
                "source": "ke-engine",
                "semantic_scoring": "human-or-calibrated-llm-judge",
            },
        )
    for case in cases:
        client.create_dataset_item(
            dataset_name=DATASET_NAME,
            **dataset_item_payload(case),
        )
    return client.get_dataset(DATASET_NAME)


def run_experiment(
    settings: Settings,
    *,
    resources: LangfuseResources | None = None,
) -> Any:
    """同步 Dataset 后串行运行真实模型实验；远端失败显式传播。"""

    active_resources = resources or create_langfuse_resources(settings)
    if active_resources is None:
        raise RuntimeError(
            "Langfuse configuration is required for the experiment"
        )
    if not settings.openai_model:
        raise RuntimeError("OPENAI_MODEL is required for the experiment")

    client = active_resources.client
    try:
        if not client.auth_check():
            raise RuntimeError("Langfuse authentication failed")
        cases = load_query_rewrite_evaluation_cases()
        dataset = sync_dataset(client, cases)
        model = create_chat_model(
            settings,
            model=settings.openai_model,
            callbacks=[active_resources.handler],
        )
        graph = build_rag_graph(model=model).compile()
        result = dataset.run_experiment(
            name="rag-query-rewrite-live-model",
            run_name=_default_run_name(),
            description=(
                "Production RAG Graph Query Rewrite against 28 labeled cases"
            ),
            task=partial(run_query_rewrite_case, graph=graph),
            evaluators=[langfuse_evaluator],
            max_concurrency=1,
            metadata={
                "model": settings.openai_model,
                "prompt_version": QUERY_REWRITE_PROMPT_VERSION,
                "app_version": settings.app_version,
                "live_model": "true",
                "semantic_scoring": "not_automated",
            },
        )
        print(result.format())
        dataset_run_url = getattr(result, "dataset_run_url", None)
        if not dataset_run_url:
            raise RuntimeError(
                "Langfuse experiment did not return a Dataset Run URL"
            )
        print(dataset_run_url)
        return result
    finally:
        client.shutdown()


def main() -> int:
    """显式 CLI；失败返回非零，避免误认为 Dataset Run 已生成。"""

    try:
        run_experiment(create_settings())
    except Exception as exc:
        print(f"Langfuse experiment failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _default_run_name() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"rag-query-rewrite-{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
