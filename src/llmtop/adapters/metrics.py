from __future__ import annotations

import math
from dataclasses import dataclass

from prometheus_client.parser import text_string_to_metric_families


class MetricError(ValueError):
    pass


@dataclass(frozen=True)
class Series:
    name: str
    labels: tuple[tuple[str, str], ...]
    value: float


def parse_metrics(text: str) -> list[Series]:
    result = []
    try:
        for family in text_string_to_metric_families(text):
            for sample in family.samples:
                result.append(
                    Series(sample.name, tuple(sorted(sample.labels.items())), float(sample.value))
                )
                if len(result) > 20000:
                    raise MetricError("Metrics response contains too many samples")
    except (ValueError, TypeError) as exc:
        if isinstance(exc, MetricError):
            raise
        raise MetricError("Malformed Prometheus exposition") from None
    return result


def select_series(
    samples: list[Series], aliases: tuple[str, ...], labels: dict[str, str]
) -> Series | None:
    for alias in aliases:
        matches = [
            s
            for s in samples
            if s.name == alias and all(dict(s.labels).get(k) == v for k, v in labels.items())
        ]
        if not matches:
            continue
        if len(matches) != 1:
            raise MetricError("Ambiguous or duplicate series; configure metric_selection labels")
        sample = matches[0]
        if not math.isfinite(sample.value) or sample.value < 0:
            raise MetricError("Metric must be finite and nonnegative")
        return sample
    return None
