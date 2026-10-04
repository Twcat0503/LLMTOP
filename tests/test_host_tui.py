import pytest
from textual.widgets import DataTable, Footer, Input, Static

from llmtop.config import HostConfig, demo_config
from llmtop.core.models import Status
from llmtop.core.runtime import Runtime
from llmtop.providers.host import HostProvider
from llmtop.providers.nvidia import NvidiaProvider, parse_smi
from llmtop.tui import MonitorApp


def test_remote_http_does_not_imply_remote_hardware():
    host = HostProvider(HostConfig(id="remote", label="Remote", collector="disabled")).collect()
    assert all(o.value is None and o.status == Status.UNSUPPORTED for o in host.metrics.values())
    assert "collector" in host.reason.lower()


def test_nvidia_units_and_partial_support():
    config = HostConfig(id="local", label="Local")
    devices = parse_smi('GPU-1, "Example, GPU", 555.1, 25, 1024, 2048, N/A, 75.5', config)
    m = devices[0].metrics
    assert devices[0].label == "Example, GPU"
    assert m["gpu_utilization_ratio"].value == 0.25
    assert m["gpu_memory_used_bytes"].value == 1073741824
    assert m["gpu_temperature_celsius"].value is None
    assert m["gpu_power_watts"].value == 75.5


def test_cpu_only_fallback(monkeypatch):
    monkeypatch.setattr("llmtop.providers.nvidia.shutil.which", lambda _: None)
    provider = NvidiaProvider(HostConfig(id="local", label="Local", gpu_provider="nvidia-smi"))
    devices, reason = provider.collect()
    assert not devices and "unavailable" in reason


async def test_stuck_gpu_is_bounded_and_does_not_accumulate_threads(config, raw_vllm, monkeypatch):
    import threading
    import time

    import httpx

    release = threading.Event()
    jobs = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, text=raw_vllm if request.url.path == "/metrics" else "ok"
            )
        )
    ) as client:
        runtime = Runtime(config, client=client)

        def stuck():
            jobs.append(1)
            release.wait(8)
            return [], None

        monkeypatch.setattr(runtime.gpus[0], "collect", stuck)
        try:
            started = time.monotonic()
            first = await runtime.poll()
            assert time.monotonic() - started < 4
            assert first.services[0].health == "reachable"
            assert "timed out" in first.hosts[0].reason
            started = time.monotonic()
            second = await runtime.poll()
            assert time.monotonic() - started < 0.5
            assert second.snapshot_seq == 2 and len(jobs) == 1
        finally:
            release.set()
            await runtime.close()


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_tui_filters_details_pause_and_shared_values(size):
    runtime = Runtime(demo_config(), demo=True)
    app = MonitorApp(runtime=runtime, ascii_only=True)
    async with app.run_test(size=size) as pilot:
        await pilot.pause(0.7)
        table = app.query_one("#services", DataTable)
        assert table.row_count == 3
        assert app.query_one("#trend", Static).region.bottom <= app.query_one(Footer).region.y
        assert app.query_one("#status", Static).region.bottom <= app.query_one(Footer).region.y
        assert table.get_row("atlas-vllm")[5:7] == ["3", "1"]
        search = app.query_one("#search", Input)
        search.value = "workbench"
        await pilot.pause()
        assert table.row_count == 1
        search.value = ""
        await pilot.pause()
        app.action_pause()
        seq = app.displayed.snapshot_seq
        await runtime.poll()
        app.refresh_snapshot()
        assert app.displayed.snapshot_seq == seq
        app.action_pause()
        assert app.displayed.snapshot_seq > seq
        table.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.screen_stack) == 2
        await pilot.press("escape")
        app.action_trend()
        assert app.trend_index == 1
    await runtime.close()
