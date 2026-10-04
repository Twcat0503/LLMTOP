from __future__ import annotations

from dataclasses import dataclass

from llmtop.core.models import Status


@dataclass(frozen=True)
class Rate:
    value: float | None
    status: Status
    window: float | None
    epoch: int
    reason: str | None = None


@dataclass
class Baseline:
    value: float
    monotonic: float
    identity: tuple
    epoch: int


class RateTracker:
    """Only compare observations with identical series identity and a fresh baseline."""

    def __init__(self, max_gap_seconds: float):
        self.max_gap = max_gap_seconds
        self.baselines: dict[tuple[str, str], Baseline] = {}
        self.epochs: dict[tuple[str, str], int] = {}

    def observe(self, source: str, metric: str, value: float, now: float, identity: tuple) -> Rate:
        key = (source, metric)
        previous = self.baselines.get(key)
        epoch = previous.epoch if previous else self.epochs.get(key, 1)
        reason = None
        if previous:
            delta = now - previous.monotonic
            if identity != previous.identity:
                reason = "Source identity or labels changed"
            elif value < previous.value:
                reason = "Counter reset"
            elif delta > self.max_gap:
                reason = "Sampling gap exceeded freshness limit"
            elif delta <= 0:
                return Rate(None, Status.WARMING_UP, None, epoch, "Awaiting a later sample")
            if reason:
                epoch += 1
            else:
                self.baselines[key] = Baseline(value, now, identity, epoch)
                return Rate((value - previous.value) / delta, Status.OK, delta, epoch)
        self.baselines[key] = Baseline(value, now, identity, epoch)
        self.epochs[key] = epoch
        return Rate(None, Status.WARMING_UP, None, epoch, reason or "Two valid samples required")

    def invalidate(self, source: str, metric: str) -> None:
        key = (source, metric)
        previous = self.baselines.pop(key, None)
        if previous:
            self.epochs[key] = previous.epoch + 1
