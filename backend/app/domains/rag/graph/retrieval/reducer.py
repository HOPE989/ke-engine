"""LangGraph 并行 Retriever outcome 的确定性 reducer。"""

from collections.abc import Mapping


def merge_retrieval_outcomes(
    left: Mapping[str, dict[str, object]] | None,
    right: Mapping[str, dict[str, object]] | None,
) -> dict[str, dict[str, object]]:
    """合并不同 Retriever 的结果，拒绝同一 superstep 的重复写入。"""

    left_values = dict(left or {})
    right_values = dict(right or {})
    duplicates = set(left_values).intersection(right_values)
    if duplicates:
        duplicate = sorted(duplicates)[0]
        raise ValueError(f"duplicate retrieval outcome: {duplicate}")
    merged = left_values | right_values
    return {key: merged[key] for key in sorted(merged)}
