from __future__ import annotations

from llmtop.core.models import Observation, Status


def number(metric: Observation | None, *, ratio: bool = False) -> str:
    if metric is None or metric.value is None or metric.status != Status.OK:
        return "N/A"
    return (
        f"{metric.value * 100:.0f}%"
        if ratio
        else f"{metric.value:,.1f}"
        if metric.unit == "tokens/s"
        else f"{metric.value:,.0f}"
    )


def gib(metric: Observation | None) -> str:
    if metric is None or metric.value is None or metric.status != Status.OK:
        return "N/A"
    return f"{metric.value / 1073741824:.1f} GiB"


def sparkline(values: list[float | None], ascii_only: bool = False) -> str:
    bars = ".:-=+*#@" if ascii_only else "▁▂▃▄▅▆▇█"
    valid = [v for v in values if v is not None]
    if not valid:
        return "N/A"
    low, high = min(valid), max(valid)
    return "".join(
        " " if v is None else bars[round((v - low) / (high - low or 1) * (len(bars) - 1))]
        for v in values
    )
