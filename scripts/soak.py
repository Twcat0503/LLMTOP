"""Bounded 30-minute collector/read-client test. All data is synthetic.

Run on the designated test VM: .venv/bin/python scripts/soak.py --seconds 1800.
Outputs no prompts, responses, credentials, or private engine metadata.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx
import psutil

from llmtop.api import create_app
from llmtop.config import Config, HostConfig, MonitorConfig, ServiceConfig
from llmtop.core.runtime import Runtime


async def run(seconds: int, destination: Path):
    started = time.monotonic()
    calls = 0
    read_calls = 0
    baseline = None

    async def engine_response(request):
        nonlocal calls
        calls += 1
        elapsed = time.monotonic() - started
        index = int(request.url.host.split("-")[-1])
        counters = f"vllm:prompt_tokens_total {int(10000 + elapsed * (20 + index))}\nvllm:generation_tokens_total {int(10000 + elapsed * (50 + index))}\nvllm:num_requests_running 2\nvllm:num_requests_waiting 1\nvllm:kv_cache_usage_perc 0.25\n"
        return httpx.Response(200, text=counters if request.url.path == "/metrics" else "ok")

    config = Config(
        hosts=[HostConfig(id="local", label="Soak host", gpu_provider="none")],
        services=[
            ServiceConfig(
                id=f"s{i}",
                label=f"Synthetic {i}",
                engine="vllm",
                host_id="local",
                api_url=f"http://engine-{i}",
            )
            for i in range(10)
        ],
        monitor=MonitorConfig(refresh_interval_seconds=2, history_seconds=600),
    )
    process = psutil.Process()
    resources = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(engine_response)) as engine:
        runtime = Runtime(config, client=engine)
        try:
            await runtime.start()
            api = create_app(runtime, manage_runtime=False)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api), base_url="http://127.0.0.1:8787"
            ) as clients:
                subscribers = [runtime.store.subscribe() for _ in range(3)]
                baseline = process.cpu_times()
                while time.monotonic() - started < seconds:
                    replies = await asyncio.gather(
                        *(clients.get("/api/v1/snapshot") for _ in range(3))
                    )
                    read_calls += 3
                    assert all(r.status_code == 200 for r in replies)
                    assert len({r.json()["snapshot_seq"] for r in replies}) == 1
                    assert all(q.qsize() <= 1 for q in subscribers)
                    resources.append(
                        {
                            "elapsed_seconds": round(time.monotonic() - started, 2),
                            "rss_bytes": process.memory_info().rss,
                            "snapshot_seq": runtime.sequence,
                            "scrapes": calls,
                        }
                    )
                    destination.write_text(
                        json.dumps(
                            {
                                "status": "running",
                                "synthetic": True,
                                "services": 10,
                                "resources": resources,
                            },
                            indent=2,
                        )
                    )
                    await asyncio.sleep(2)
                for queue in subscribers:
                    runtime.store.unsubscribe(queue)
            cpu = process.cpu_times()
            elapsed = time.monotonic() - started
            assert calls == runtime.sequence * 20
            assert len(runtime.store.history) <= 302
            result = {
                "status": "passed",
                "synthetic": True,
                "duration_seconds": round(elapsed, 2),
                "services": 10,
                "interval_seconds": 2,
                "snapshot_count": runtime.sequence,
                "source_gets": calls,
                "expected_source_gets": runtime.sequence * 20,
                "client_reads": read_calls,
                "average_process_cpu_percent_one_core": round(
                    (cpu.user + cpu.system - baseline.user - baseline.system) / elapsed * 100, 3
                ),
                "rss_min_bytes": min(r["rss_bytes"] for r in resources),
                "rss_max_bytes": max(r["rss_bytes"] for r in resources),
                "history_samples": len(runtime.store.history),
                "resources": resources,
            }
            destination.write_text(json.dumps(result, indent=2))
        finally:
            await runtime.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--output", type=Path, default=Path("artifacts/soak.json"))
    args = parser.parse_args()
    asyncio.run(run(args.seconds, args.output))
