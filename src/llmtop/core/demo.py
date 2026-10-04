from __future__ import annotations

import math

from llmtop.adapters.engines import EngineAdapter, Health
from llmtop.adapters.metrics import Series
from llmtop.config import Config
from llmtop.core.models import Device, Host, Observation, Status, utc_now
from llmtop.providers.host import HOST_FIELDS
from llmtop.providers.nvidia import gpu_observations


class Demo:
    """Explicit synthetic input that exercises the same engine normalization and rate paths."""

    def __init__(self, config: Config, adapters: list[EngineAdapter]):
        self.config = config
        self.adapters = adapters
        self.started: float | None = None
        self.previous: float | None = None
        self.counters = {adapter.config.id: [12000.0, 48000.0] for adapter in adapters}

    def collect(self, monotonic: float):
        if self.started is None:
            self.started = monotonic
        elapsed = monotonic - self.started
        delta = monotonic - self.previous if self.previous is not None else 0
        self.previous = monotonic
        services = []
        for index, adapter in enumerate(self.adapters):
            if index == 2:
                services.append(adapter.failure("Connection timed out", Health.UNREACHABLE))
                continue
            input_tps = 82.1 if index == 0 else 24.0
            output_tps = (142.8 if index == 0 else 41.8) + (12 if index == 0 else 4) * math.sin(
                elapsed / 12
            )
            counters = self.counters[adapter.config.id]
            counters[0] += input_tps * delta
            counters[1] += output_tps * delta
            labels = tuple(sorted(adapter.config.metric_selection.items()))
            prefix = "vllm" if index == 0 else "llamacpp"
            samples = [
                Series(f"{prefix}:prompt_tokens_total", labels, counters[0]),
                Series(
                    f"{prefix}:generation_tokens_total"
                    if index == 0
                    else "llamacpp:tokens_predicted_total",
                    labels,
                    counters[1],
                ),
                Series(
                    "vllm:num_requests_running" if index == 0 else "llamacpp:requests_processing",
                    labels,
                    3.0 if index == 0 else 1.0,
                ),
                Series(
                    "vllm:num_requests_waiting" if index == 0 else "llamacpp:requests_deferred",
                    labels,
                    1.0 if index == 0 else 0.0,
                ),
            ]
            if index == 0:
                samples.append(Series("vllm:kv_cache_usage_perc", labels, 0.37))
            service = adapter.normalize(samples, monotonic)
            adapter.previous = service
            services.append(service)
        config = self.config.hosts[0]
        values = {
            "host_cpu_usage_ratio": 0.34,
            "host_ram_total_bytes": 47 * 1073741824,
            "host_ram_available_bytes": (47 - 19.2) * 1073741824,
            "host_ram_usage_ratio": 19.2 / 47,
            "host_swap_total_bytes": 8 * 1073741824,
            "host_swap_used_bytes": 0.8 * 1073741824,
            "collector_rss_bytes": 32 * 1048576,
        }
        now = utc_now()
        metrics = {
            name: Observation(
                metric=name,
                value=value,
                unit=HOST_FIELDS[name],
                status=Status.OK,
                host_id=config.id,
                source_kind="demo",
                scope="vm",
                observed_at=now,
                last_success_at=now,
                reason="Synthetic example value",
            )
            for name, value in values.items()
        }
        gpu = Device(
            id="demo-gpu",
            label="NVIDIA GPU",
            provider="demo",
            metrics=gpu_observations(
                config,
                "demo-gpu",
                {
                    "gpu_utilization_ratio": 0.46,
                    "gpu_memory_used_bytes": 9.1 * 1073741824,
                    "gpu_memory_total_bytes": 24 * 1073741824,
                    "gpu_temperature_celsius": 54,
                    "gpu_power_watts": 112,
                },
                "demo",
            ),
        )
        return services, [
            Host(
                id=config.id,
                label=config.label,
                scope="vm",
                collector="demo",
                metrics=metrics,
                devices=[gpu],
            )
        ]
