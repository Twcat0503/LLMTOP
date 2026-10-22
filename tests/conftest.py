from pathlib import Path

import pytest

from llmtop.config import Config, HostConfig, MonitorConfig, ServiceConfig


@pytest.fixture
def config():
    return Config(
        hosts=[HostConfig(id="host", label="Fixture host", gpu_provider="none")],
        services=[
            ServiceConfig(
                id="service",
                label="Fixture service",
                host_id="host",
                engine="vllm",
                api_url="http://engine.test",
            )
        ],
        monitor=MonitorConfig(refresh_interval_seconds=0.25, stale_after_seconds=1),
    )


@pytest.fixture
def raw_vllm():
    return (Path(__file__).parent / "fixtures/vllm.prom").read_text()


@pytest.fixture
def raw_llama():
    return (Path(__file__).parent / "fixtures/llamacpp.prom").read_text()


@pytest.fixture
def raw_strata():
    return (Path(__file__).parent / "fixtures/strata.prom").read_text()
