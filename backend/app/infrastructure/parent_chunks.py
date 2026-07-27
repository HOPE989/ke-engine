"""父分段正文的本地、Redis、PostgreSQL 三级读取。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_KEY_PREFIX = "rag:parent-chunk"
_MISSING_SENTINEL = "\x00"


@dataclass(frozen=True, slots=True)
class CachedParentChunkLoader:
    """按方法级本地缓存 → Redis → PostgreSQL 的顺序读取父分段。"""

    repository: Any
    redis_client: Any
    cache_ttl_seconds: int = 30
    missing_cache_ttl_seconds: int = 30

    async def load(
        self,
        references: Sequence[tuple[str, str]],
    ) -> dict[tuple[str, str], str]:
        """批量读取父分段，并在一次调用内复用相同引用的读取结果。"""

        ordered_references = _unique_references(references)
        if not ordered_references:
            return {}

        local_cache: dict[tuple[str, str], str | None] = {}
        redis_misses: list[tuple[str, str]] = []
        redis_values = await self._read_redis(ordered_references)

        for reference, cached_value in zip(
            ordered_references,
            redis_values,
            strict=True,
        ):
            decoded = _decode_cached_value(cached_value)
            if decoded is _CACHE_MISS:
                redis_misses.append(reference)
                continue
            local_cache[reference] = decoded

        if redis_misses:
            database_values = await self.repository.get_parent_texts(
                redis_misses
            )
            for reference in redis_misses:
                local_cache[reference] = database_values.get(reference)
            await self._write_redis(redis_misses, local_cache)

        return {
            reference: text
            for reference, text in local_cache.items()
            if text is not None
        }

    async def _read_redis(
        self,
        references: Sequence[tuple[str, str]],
    ) -> list[Any]:
        keys = [_cache_key(reference) for reference in references]
        try:
            values = await asyncio.to_thread(
                self.redis_client.mget,
                keys,
            )
        except Exception:
            logger.warning(
                "parent chunk Redis read failed; falling back to PostgreSQL",
                exc_info=True,
            )
            return [None] * len(keys)
        if not isinstance(values, (list, tuple)) or len(values) != len(keys):
            logger.warning(
                "parent chunk Redis mget returned an invalid response; "
                "falling back to PostgreSQL"
            )
            return [None] * len(keys)
        return list(values)

    async def _write_redis(
        self,
        references: Sequence[tuple[str, str]],
        local_cache: dict[tuple[str, str], str | None],
    ) -> None:
        def write() -> None:
            pipeline = self.redis_client.pipeline(transaction=False)
            for reference in references:
                text = local_cache[reference]
                pipeline.set(
                    _cache_key(reference),
                    text if text is not None else _MISSING_SENTINEL,
                    ex=(
                        self.cache_ttl_seconds
                        if text is not None
                        else self.missing_cache_ttl_seconds
                    ),
                )
            pipeline.execute()

        try:
            await asyncio.to_thread(write)
        except Exception:
            logger.warning(
                "parent chunk Redis write failed; returning PostgreSQL data",
                exc_info=True,
            )


class _CacheMiss:
    pass


_CACHE_MISS = _CacheMiss()


def _unique_references(
    references: Sequence[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    unique: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for doc_id, parent_chunk_id in references:
        reference = (doc_id.strip(), parent_chunk_id.strip())
        if not reference[0] or not reference[1]:
            raise ValueError("parent chunk reference must be non-blank")
        if reference in seen:
            continue
        seen.add(reference)
        unique.append(reference)
    return tuple(unique)


def _cache_key(reference: tuple[str, str]) -> str:
    doc_id, parent_chunk_id = reference
    return f"{_CACHE_KEY_PREFIX}:{doc_id}:{parent_chunk_id}"


def _decode_cached_value(value: Any) -> str | None | _CacheMiss:
    if value is None:
        return _CACHE_MISS
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str):
        return _CACHE_MISS
    if value == _MISSING_SENTINEL:
        return None
    return value
