"""Snowflake 风格的 64 位 ID 生成器。"""

from __future__ import annotations

import threading
import time

EPOCH_MILLIS = 1_704_067_200_000  # 2024-01-01T00:00:00Z
WORKER_ID_BITS = 10
SEQUENCE_BITS = 12
MAX_WORKER_ID = (1 << WORKER_ID_BITS) - 1
MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1
WORKER_ID_SHIFT = SEQUENCE_BITS
TIMESTAMP_SHIFT = WORKER_ID_BITS + SEQUENCE_BITS


def current_time_millis() -> int:
    """返回当前 Unix 毫秒时间。"""

    return int(time.time() * 1000)


class SnowflakeIdGenerator:
    """生成趋势递增的 64 位整型 ID。"""

    def __init__(self, *, worker_id: int) -> None:
        if worker_id < 0 or worker_id > MAX_WORKER_ID:
            raise ValueError("snowflake worker_id must be between 0 and 1023")
        self._worker_id = worker_id
        self._lock = threading.Lock()
        self._last_timestamp = -1
        self._sequence = 0

    def next_id(self) -> int:
        """生成下一个 ID。"""

        with self._lock:
            timestamp = current_time_millis()
            if timestamp < self._last_timestamp:
                timestamp = self._last_timestamp

            if timestamp == self._last_timestamp:
                self._sequence = (self._sequence + 1) & MAX_SEQUENCE
                if self._sequence == 0:
                    timestamp = self._wait_next_millis(timestamp)
            else:
                self._sequence = 0

            self._last_timestamp = timestamp
            return (
                ((timestamp - EPOCH_MILLIS) << TIMESTAMP_SHIFT)
                | (self._worker_id << WORKER_ID_SHIFT)
                | self._sequence
            )

    def _wait_next_millis(self, timestamp: int) -> int:
        """同一毫秒序列耗尽时等待下一毫秒。"""

        next_timestamp = current_time_millis()
        while next_timestamp <= timestamp:
            time.sleep(0.001)
            next_timestamp = current_time_millis()
        return next_timestamp
