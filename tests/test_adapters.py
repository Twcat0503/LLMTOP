import asyncio
from datetime import timedelta

import httpx
import pytest

from llmtop.adapters.engines import EngineAdapter, Fetcher
from llmtop.adapters.metrics import MetricError, parse_metrics, select_series
from llmtop.config import AuthConfig, MonitorConfig
from llmtop.core.models import Health, Status, utc_now
from llmtop.core.rates import RateTracker


def adapter(config, client=None):
    return EngineAdapter(
        config.services[0],
        Fetcher(client, config.monitor),
        RateTracker(config.monitor.stale_after_seconds),
    )


def test_vllm_normalization_aliases_and_actual_rates(config, raw_vllm):
    config = config.model_copy(update={"monitor": MonitorConfig()})
    engine = adapter(config)
    first = engine.normalize(parse_metrics(raw_vllm), 10)
    second = engine.normalize(
        parse_metrics(raw_vllm.replace(" 1000", " 1040").replace(" 2000", " 2080")), 12
    )
    assert first.metrics["input_tps"].status == Status.WARMING_UP
    assert second.metrics["input_tps"].value == 20
    assert second.metrics["output_tps"].value == 40
    assert second.metrics["kv_cache_usage_ratio"].value == 0.375
    assert second.metrics["engine_running_requests"].value == 2
    legacy = engine.normalize(
        parse_metrics(raw_vllm.replace("kv_cache_usage_perc", "gpu_cache_usage_perc")), 14
    )
    assert legacy.metrics["kv_cache_usage_ratio"].source_metric == "vllm:gpu_cache_usage_perc"


def test_llama_context_is_not_kv(config, raw_llama):
    service = config.services[0].model_copy(update={"engine": "llamacpp"})
    engine = EngineAdapter(service, Fetcher(None, config.monitor), RateTracker(10))
    result = engine.normalize(parse_metrics(raw_llama), 1)
    assert result.metrics["engine_prompt_tokens_total"].value == 500
    assert result.metrics["engine_waiting_requests"].value == 0
    assert result.metrics["kv_cache_usage_ratio"].value is None
    assert result.metrics["kv_cache_usage_ratio"].status == Status.UNSUPPORTED


def test_reset_of_one_counter_rebaselines_both_rates(config, raw_vllm):
    engine = adapter(config)
    engine.normalize(parse_metrics(raw_vllm), 10)
    restarted = raw_vllm.replace(" 1000", " 5").replace(" 2000", " 2050")
    result = engine.normalize(parse_metrics(restarted), 10.5)
    assert result.metrics["input_tps"].status == Status.WARMING_UP
    assert result.metrics["output_tps"].status == Status.WARMING_UP
    assert result.metrics["input_tps"].epoch == "2"
    assert result.metrics["output_tps"].epoch == "2"


def test_ambiguous_replicas_are_not_added(config, raw_vllm):
    more = raw_vllm + '\nvllm:prompt_tokens_total{model_name="fixture-model",engine="1"} 3000\n'
    result = adapter(config).normalize(parse_metrics(more), 1)
    assert result.health == Health.DEGRADED
    assert result.metrics["engine_prompt_tokens_total"].value is None
    selected = config.model_copy(
        update={
            "services": [
                config.services[0].model_copy(update={"metric_selection": {"engine": "0"}})
            ]
        }
    )
    assert (
        adapter(selected)
        .normalize(parse_metrics(more), 1)
        .metrics["engine_prompt_tokens_total"]
        .value
        == 1000
    )


@pytest.mark.parametrize("metric", ["x NaN", "x +Inf", "x -2", "x 1\nx 2"])
def test_invalid_or_duplicate_series(metric):
    with pytest.raises(MetricError):
        select_series(parse_metrics(metric), ("x",), {})


def test_missing_labels_and_missing_counter_reset_baseline(config, raw_vllm):
    engine = adapter(config)
    engine.normalize(parse_metrics(raw_vllm), 1)
    missing = engine.normalize([], 3)
    assert missing.metrics["output_tps"].value is None
    recovered = engine.normalize(parse_metrics(raw_vllm), 5)
    assert recovered.metrics["output_tps"].status == Status.WARMING_UP
    selected = config.model_copy(
        update={
            "services": [
                config.services[0].model_copy(update={"metric_selection": {"model_name": "absent"}})
            ]
        }
    )
    assert (
        adapter(selected).normalize(parse_metrics(raw_vllm), 1).metrics["input_tps"].status
        == Status.NO_DATA
    )


@pytest.mark.parametrize("replace", [("0.375", "37.5"), ("} 2\n", "} 2.5\n")])
def test_ratio_and_integer_contract(config, raw_vllm, replace):
    result = adapter(config).normalize(parse_metrics(raw_vllm.replace(*replace)), 1)
    assert result.health == Health.DEGRADED


@pytest.mark.parametrize(
    "code,health,status",
    [
        (401, Health.AUTH_ERROR, Status.PERMISSION_DENIED),
        (403, Health.AUTH_ERROR, Status.PERMISSION_DENIED),
        (500, Health.DEGRADED, Status.UNAVAILABLE),
    ],
)
async def test_http_failures_do_not_expose_response_secrets(config, code, health, status):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(code, text="private-token"))
    ) as client:
        result = await adapter(config, client).collect()
    assert result.health == health
    assert result.metrics["output_tps"].status == status
    assert "private-token" not in result.model_dump_json()


async def test_timeout_is_bounded_and_never_posts(config):
    calls = []

    async def respond(request):
        calls.append(request.method)
        await asyncio.sleep(0.2)
        return httpx.Response(200)

    config = config.model_copy(update={"monitor": MonitorConfig(http_timeout_seconds=0.03)})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await adapter(config, client).collect()
    assert calls == ["GET", "GET"]
    assert result.health == Health.UNREACHABLE
    assert "timed out" in result.reason


async def test_missing_credential_has_no_network(config, monkeypatch):
    service = config.services[0].model_copy(
        update={"metrics_auth": AuthConfig(kind="bearer", token_env="LLMTOP_TEST_SECRET")}
    )
    config = config.model_copy(update={"services": [service]})
    monkeypatch.delenv("LLMTOP_TEST_SECRET", raising=False)
    result = await adapter(config).collect()
    assert result.health == Health.AUTH_ERROR


async def test_bearer_is_server_only_and_response_size_is_bounded(config, monkeypatch, raw_vllm):
    monkeypatch.setenv("LLMTOP_TEST_SECRET", "private-token")
    service = config.services[0].model_copy(
        update={"metrics_auth": AuthConfig(kind="bearer", token_env="LLMTOP_TEST_SECRET")}
    )
    config = config.model_copy(
        update={"services": [service], "monitor": MonitorConfig(max_response_bytes=1024)}
    )

    def respond(request):
        if request.url.path == "/metrics":
            assert request.headers["authorization"] == "Bearer private-token"
            return httpx.Response(200, text=raw_vllm * 4)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await adapter(config, client).collect()
    assert "size limit" in result.reason
    assert "private-token" not in result.model_dump_json()


async def test_malformed_health_loading_and_optional_slots(config, raw_llama):
    service = config.services[0].model_copy(update={"engine": "llamacpp", "slots_path": "/slots"})
    config = config.model_copy(update={"services": [service]})

    def respond(request):
        return (
            httpx.Response(503)
            if request.url.path == "/health"
            else httpx.Response(200, json=[{"id": 0, "is_processing": True}])
            if request.url.path == "/slots"
            else httpx.Response(200, text=raw_llama)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await adapter(config, client).collect()
    assert result.health == Health.LOADING
    assert any(c.metric == "slot_states" for c in result.capabilities)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x {invalid"))
    ) as client:
        result = await adapter(config, client).collect()
    assert result.metrics["output_tps"].status == Status.ERROR


def test_failure_freshness_preserves_last_success(config, raw_vllm):
    engine = adapter(config)
    first = engine.normalize(parse_metrics(raw_vllm), 1)
    old = utc_now() - timedelta(seconds=20)
    engine.previous = first.model_copy(
        update={
            "metrics": {
                name: m.model_copy(update={"last_success_at": old})
                for name, m in first.metrics.items()
            }
        }
    )
    failed = engine.failure("Connection timed out", Health.UNREACHABLE)
    assert failed.metrics["output_tps"].value is None
    assert failed.metrics["output_tps"].status == Status.STALE
    assert failed.metrics["output_tps"].last_success_at == old
