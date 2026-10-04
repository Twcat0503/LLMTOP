from __future__ import annotations

import asyncio
import math
from collections import deque
from datetime import timedelta

from llmtop.core.models import Snapshot, Status, utc_now

HISTORY_METRICS = {
    "input_tps",
    "output_tps",
    "engine_running_requests",
    "engine_waiting_requests",
    "kv_cache_usage_ratio",
    "host_cpu_usage_ratio",
    "host_ram_usage_ratio",
}


class Store:
    def __init__(self, history_seconds: int, interval: float):
        self.history_seconds = history_seconds
        self.current: Snapshot | None = None
        self.serialized: str | None = None
        self.history: deque[Snapshot] = deque(
            maxlen=min(1800, math.ceil(history_seconds / interval) + 2)
        )
        self.subscribers: set[asyncio.Queue[Snapshot]] = set()

    def publish(self, snapshot: Snapshot) -> None:
        self.current = snapshot
        self.serialized = snapshot.model_dump_json()
        self.history.append(snapshot)
        cutoff = snapshot.collected_at - timedelta(seconds=self.history_seconds)
        while self.history and self.history[0].collected_at < cutoff:
            self.history.popleft()
        for queue in tuple(self.subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(snapshot)

    def subscribe(self) -> asyncio.Queue[Snapshot]:
        if len(self.subscribers) >= 64:
            raise ValueError("Maximum stream clients reached")
        queue: asyncio.Queue[Snapshot] = asyncio.Queue(maxsize=1)
        self.subscribers.add(queue)
        if self.current:
            queue.put_nowait(self.current)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Snapshot]) -> None:
        self.subscribers.discard(queue)

    def series(self, ids: list[str], metric: str, window_seconds: float, limit: int) -> dict:
        cutoff = utc_now() - timedelta(seconds=window_seconds)
        selected = [s for s in self.history if s.collected_at >= cutoff]
        truncated = len(selected) > limit
        selected = selected[-limit:]
        series = []
        for identity in ids:
            points = []
            unit = None
            for snapshot in selected:
                entities = [*snapshot.services, *snapshot.hosts]
                entity = next((e for e in entities if e.id == identity), None)
                observation = entity.metrics.get(metric) if entity else None
                if observation:
                    unit = observation.unit
                    points.append(
                        {
                            "timestamp": snapshot.collected_at.isoformat(),
                            "snapshot_seq": snapshot.snapshot_seq,
                            "value": observation.value if observation.status == Status.OK else None,
                            "status": observation.status,
                        }
                    )
            series.append({"id": identity, "metric": metric, "unit": unit, "points": points})
        return {
            "schema_version": 1,
            "runtime_id": self.current.runtime_id if self.current else None,
            "window_seconds": window_seconds,
            "truncated": truncated,
            "series": series,
        }
