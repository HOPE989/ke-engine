"""Agent 检索重排组件。"""

from typing import TypeVar

T = TypeVar("T")


def keep_original_order(items: list[T]) -> list[T]:
    """默认重排策略：保持原顺序。"""

    return list(items)
