"""Magika 文件类型检测器的项目级访问器。"""

from functools import lru_cache

from magika import Magika


@lru_cache
def get_magika_client() -> Magika:
    """创建并缓存 Magika detector。"""

    return Magika()
