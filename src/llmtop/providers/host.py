from __future__ import annotations

import psutil

from llmtop.config import HostConfig
from llmtop.core.models import Host, Observation, Status, utc_now

HOST_FIELDS = {
    "host_cpu_usage_ratio": "ratio",
    "host_ram_total_bytes": "bytes",
    "host_ram_available_bytes": "bytes",
    "host_ram_usage_ratio": "ratio",
    "host_swap_total_bytes": "bytes",
    "host_swap_used_bytes": "bytes",
    "collector_rss_bytes": "bytes",
}


class HostProvider:
    def __init__(self, config: HostConfig):
        self.config = config
        self.warmed = False

    def collect(self) -> Host:
        config = self.config
        now = utc_now()
        values = {}
        reason = None
        if config.collector == "local":
            try:
                memory = psutil.virtual_memory()
                swap = psutil.swap_memory()
                values = {
                    "host_cpu_usage_ratio": psutil.cpu_percent(interval=None) / 100,
                    "host_ram_total_bytes": memory.total,
                    "host_ram_available_bytes": memory.available,
                    "host_ram_usage_ratio": (memory.total - memory.available) / memory.total,
                    "host_swap_total_bytes": swap.total,
                    "host_swap_used_bytes": swap.used,
                    "collector_rss_bytes": psutil.Process().memory_info().rss,
                }
            except (OSError, psutil.Error):
                reason = "Local OS metrics are unavailable or permission was denied"
        else:
            reason = "Remote hardware requires a collector on that host"
        observations = {}
        for metric, unit in HOST_FIELDS.items():
            value = values.get(metric)
            status = (
                Status.OK
                if value is not None
                else Status.UNSUPPORTED
                if config.collector == "disabled"
                else Status.UNAVAILABLE
            )
            field_reason = reason
            if metric == "host_cpu_usage_ratio" and value is not None and not self.warmed:
                value, status, field_reason = (
                    None,
                    Status.WARMING_UP,
                    "CPU sampling requires a baseline",
                )
            observations[metric] = Observation(
                metric=metric,
                value=value,
                unit=unit,
                status=status,
                host_id=config.id,
                source_kind="host_provider",
                source_metric=f"psutil.{metric}",
                scope=config.hardware_scope,
                observed_at=now,
                last_success_at=now if status == Status.OK else None,
                reason=field_reason,
            )
        self.warmed = bool(values)
        return Host(
            id=config.id,
            label=config.label,
            collector=config.collector,
            scope=config.hardware_scope,
            metrics=observations,
            reason=reason,
        )
