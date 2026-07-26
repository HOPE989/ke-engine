"""验证所有已计划 Retriever 均已产生 outcome。"""

from app.domains.rag.graph.query_router import RetrievalPlan
from app.domains.rag.graph.state import RagState


class MissingRetrievalOutcome(Exception):
    """检索计划与实际 outcome 不完整。"""


def collect_retrieval_outcomes_node(
    state: RagState,
) -> dict[str, object]:
    plan = RetrievalPlan.model_validate(state["retrieval_plan"])
    outcomes = state.get("retrieval_outcomes", {})
    missing = [
        retriever.value
        for retriever in plan.selected_retrievers
        if retriever.value not in outcomes
    ]
    if missing:
        raise MissingRetrievalOutcome(
            f"missing retrieval outcomes: {', '.join(missing)}"
        )
    return {}
