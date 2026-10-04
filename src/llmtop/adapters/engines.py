from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urljoin

import httpx

from llmtop.adapters.metrics import MetricError, Series, parse_metrics, select_series
from llmtop.config import ConfigError, MonitorConfig, ServiceConfig
from llmtop.core.models import Capability, Health, Observation, Service, Status, utc_now
from llmtop.core.rates import RateTracker

MAPPINGS = {
    "vllm": {
        "engine_prompt_tokens_total": (
            "tokens",
            ("vllm:prompt_tokens_total", "vllm:prompt_tokens"),
        ),
        "engine_generation_tokens_total": (
            "tokens",
            ("vllm:generation_tokens_total", "vllm:generation_tokens"),
        ),
        "engine_running_requests": ("requests", ("vllm:num_requests_running",)),
        "engine_waiting_requests": ("requests", ("vllm:num_requests_waiting",)),
        "kv_cache_usage_ratio": (
            "ratio",
            ("vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc"),
        ),
    },
    "llamacpp": {
        "engine_prompt_tokens_total": ("tokens", ("llamacpp:prompt_tokens_total",)),
        "engine_generation_tokens_total": ("tokens", ("llamacpp:tokens_predicted_total",)),
        "engine_running_requests": ("requests", ("llamacpp:requests_processing",)),
        "engine_waiting_requests": ("requests", ("llamacpp:requests_deferred",)),
        "kv_cache_usage_ratio": ("ratio", ()),
    },
}
RATE_NAMES = {
    "engine_prompt_tokens_total": "input_tps",
    "engine_generation_tokens_total": "output_tps",
}


class PollError(Exception):
    def __init__(self, reason: str, health: Health = Health.UNREACHABLE):
        self.reason = reason
        self.health = health
        super().__init__(reason)


class Fetcher:
    def __init__(self, client: httpx.AsyncClient, monitor: MonitorConfig):
        self.client = client
        self.monitor = monitor
        self.semaphore = asyncio.Semaphore(monitor.max_concurrent_polls)

    async def get(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        async def request():
            async with self.semaphore, self.client.stream("GET", url, headers=headers) as response:
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self.monitor.max_response_bytes:
                        raise PollError("Response exceeded configured size limit", Health.DEGRADED)
                    chunks.append(chunk)
                return response.status_code, b"".join(chunks)

        try:
            return await asyncio.wait_for(request(), timeout=self.monitor.http_timeout_seconds)
        except (httpx.TimeoutException, TimeoutError):
            raise PollError("Connection timed out") from None
        except httpx.HTTPError:
            raise PollError("Connection failed") from None


class EngineAdapter:
    def __init__(self, config: ServiceConfig, fetcher: Fetcher, rates: RateTracker):
        self.config = config
        self.fetcher = fetcher
        self.rates = rates
        self.previous: Service | None = None

    async def collect(self) -> Service:
        config = self.config
        if config.engine not in MAPPINGS:
            return self.failure(
                "This engine adapter is scheduled for M2", Health.UNKNOWN, Status.UNSUPPORTED
            )
        try:
            api_headers = config.api_auth.headers()
            metric_headers = config.metrics_auth.headers()
        except ConfigError:
            return self.failure(
                "Credential environment variable is unavailable",
                Health.AUTH_ERROR,
                Status.PERMISSION_DENIED,
            )
        metrics_url = config.metrics_url or config.api_url + "/metrics"
        health_url = urljoin(config.api_url + "/", config.health_path.lstrip("/"))
        health_result, metrics_result = await asyncio.gather(
            self.fetcher.get(health_url, api_headers),
            self.fetcher.get(metrics_url, metric_headers),
            return_exceptions=True,
        )
        health = Health.REACHABLE
        reason = None
        if isinstance(health_result, PollError):
            health, reason = health_result.health, health_result.reason
        elif isinstance(health_result, Exception):
            health, reason = Health.UNKNOWN, "Health check failed"
        elif health_result[0] in {401, 403}:
            health, reason = Health.AUTH_ERROR, "Health endpoint authentication failed"
        elif health_result[0] == 503:
            health, reason = Health.LOADING, "Engine is loading or not ready"
        elif health_result[0] != 200:
            health, reason = Health.UNKNOWN, f"Health endpoint returned HTTP {health_result[0]}"
        if isinstance(metrics_result, PollError):
            return self.failure(
                metrics_result.reason,
                health if health != Health.REACHABLE else metrics_result.health,
            )
        if isinstance(metrics_result, Exception):
            return self.failure("Metrics collection failed", Health.DEGRADED)
        if metrics_result[0] in {401, 403}:
            return self.failure(
                "Metrics endpoint authentication failed",
                Health.AUTH_ERROR,
                Status.PERMISSION_DENIED,
            )
        if metrics_result[0] != 200:
            return self.failure(
                f"Metrics endpoint returned HTTP {metrics_result[0]}", Health.DEGRADED
            )
        try:
            samples = parse_metrics(metrics_result[1].decode("utf-8"))
        except (MetricError, UnicodeError):
            return self.failure("Malformed metrics response", Health.DEGRADED, Status.ERROR)
        service = self.normalize(samples, time.monotonic(), health, reason)
        if config.engine == "llamacpp" and config.slots_path:
            # Slots are optional live observations, never cumulative counters or waiting lists.
            try:
                code, body = await self.fetcher.get(
                    urljoin(config.api_url + "/", config.slots_path.lstrip("/")), api_headers
                )
                slots = json.loads(body) if code == 200 else None
                if isinstance(slots, list):
                    service = service.model_copy(
                        update={
                            "capabilities": [
                                *service.capabilities,
                                Capability(
                                    metric="slot_states",
                                    support="conditional",
                                    source="slots",
                                    reason="Live slots only; not a complete request lifecycle",
                                ),
                            ]
                        }
                    )
            except (PollError, ValueError):
                pass
        self.previous = service
        return service

    def normalize(
        self,
        samples: list[Series],
        monotonic: float,
        health: Health = Health.REACHABLE,
        reason: str | None = None,
    ) -> Service:
        config = self.config
        now = utc_now()
        observations = {}
        capabilities = []
        start_times = [
            s.value for s in samples if s.name == "process_start_time_seconds" and not s.labels
        ]
        start_time = tuple(start_times)
        selection = config.metric_selection
        observed_models = set()
        # A decrease in either native token counter is evidence of a new epoch.
        # Rebaseline both rates so a partially reset pair cannot mix engine runs.
        counter_reset = False
        for counter in RATE_NAMES:
            try:
                current = select_series(samples, MAPPINGS[config.engine][counter][1], selection)
            except MetricError:
                continue
            previous = self.rates.baselines.get((config.id, counter))
            if current and previous and current.value < previous.value:
                counter_reset = True
        if counter_reset:
            for counter in RATE_NAMES:
                self.rates.invalidate(config.id, counter)
        for metric, (unit, aliases) in MAPPINGS[config.engine].items():
            status = Status.NO_DATA if aliases else Status.UNSUPPORTED
            field_reason = (
                "Metric not exposed by this deployment"
                if aliases
                else "No verified native KV occupancy metric"
            )
            sample = None
            try:
                sample = select_series(samples, aliases, selection)
                if sample and unit == "ratio" and sample.value > 1:
                    raise MetricError("Ratio is outside 0–1")
                if sample and unit == "requests" and not sample.value.is_integer():
                    raise MetricError("Request count is not an integer")
                if sample:
                    status, field_reason = Status.OK, None
                    model_name = dict(sample.labels).get("model_name")
                    if model_name:
                        observed_models.add(model_name)
            except MetricError as exc:
                sample = None
                status, field_reason = Status.ERROR, str(exc)
            observation = Observation(
                metric=metric,
                value=sample.value if sample else None,
                unit=unit,
                status=status,
                host_id=config.host_id,
                service_id=config.id,
                model_id=selection.get("model_name"),
                source_kind="engine_metrics",
                source_metric=sample.name if sample else (aliases[0] if aliases else None),
                observed_at=now,
                last_success_at=now if sample else None,
                coverage="complete" if sample else "unknown",
                semantics="engine_processed"
                if unit == "tokens"
                else "native_scheduler"
                if unit == "requests"
                else "native_kv_pool",
                reason=field_reason,
            )
            observations[metric] = observation
            capabilities.append(
                Capability(
                    metric=metric,
                    support="supported" if sample else "conditional" if aliases else "unsupported",
                    source=observation.source_metric,
                    reason=field_reason,
                )
            )
            if metric in RATE_NAMES:
                rate_name = RATE_NAMES[metric]
                rate = (
                    self.rates.observe(
                        config.id,
                        metric,
                        sample.value,
                        monotonic,
                        (config.engine, start_time, sample.labels),
                    )
                    if sample
                    else None
                )
                if not sample:
                    self.rates.invalidate(config.id, metric)
                observations[rate_name] = observation.model_copy(
                    update={
                        "metric": rate_name,
                        "unit": "tokens/s",
                        "value": rate.value if rate else None,
                        "status": rate.status if rate else status,
                        "window_seconds": rate.window if rate else None,
                        "epoch": str(rate.epoch) if rate else None,
                        "reason": rate.reason if rate else field_reason,
                        "measurement_kind": "derived",
                    }
                )
        if (
            not any(o.status == Status.OK for o in observations.values())
            and health == Health.REACHABLE
        ):
            health, reason = Health.DEGRADED, "No usable metric series exposed by this deployment"
        elif (
            any(o.status == Status.ERROR for o in observations.values())
            and health == Health.REACHABLE
        ):
            health = Health.DEGRADED
            reason = "Some metric series are invalid or ambiguous"
        return Service(
            id=config.id,
            label=config.label,
            host_id=config.host_id,
            engine=config.engine,
            model_name=selection.get("model_name")
            or (next(iter(observed_models)) if len(observed_models) == 1 else None),
            engine_version=config.engine_version,
            health=health,
            reason=reason,
            metrics=observations,
            capabilities=capabilities,
            selected_labels=selection,
            last_success_at=now,
        )

    def failure(self, reason: str, health: Health, status: Status = Status.UNAVAILABLE) -> Service:
        config = self.config
        now = utc_now()
        observations = {}
        mapping = MAPPINGS.get(config.engine, MAPPINGS["vllm"])
        for metric, (unit, aliases) in mapping.items():
            old = self.previous.metrics.get(metric) if self.previous else None
            stale = (
                old
                and old.last_success_at
                and (now - old.last_success_at).total_seconds()
                > self.fetcher.monitor.stale_after_seconds
            )
            observation = Observation(
                metric=metric,
                unit=unit,
                status=Status.STALE if stale else status,
                host_id=config.host_id,
                service_id=config.id,
                source_kind="engine_metrics",
                source_metric=aliases[0] if aliases else None,
                observed_at=now,
                last_success_at=old.last_success_at if old else None,
                reason=reason,
            )
            observations[metric] = observation
            if metric in RATE_NAMES:
                observations[RATE_NAMES[metric]] = observation.model_copy(
                    update={
                        "metric": RATE_NAMES[metric],
                        "unit": "tokens/s",
                        "measurement_kind": "derived",
                    }
                )
        result = Service(
            id=config.id,
            label=config.label,
            host_id=config.host_id,
            engine=config.engine,
            model_name=config.metric_selection.get("model_name"),
            engine_version=config.engine_version,
            health=health,
            reason=reason,
            metrics=observations,
            last_success_at=self.previous.last_success_at if self.previous else None,
            capabilities=[
                Capability(metric=m, support="unknown", reason=reason) for m in observations
            ],
        )
        self.previous = result
        return result
