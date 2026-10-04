from __future__ import annotations

import asyncio
import threading
import time
import uuid
from contextlib import suppress

import httpx

from llmtop.adapters.engines import EngineAdapter, Fetcher
from llmtop.config import Config
from llmtop.core.demo import Demo
from llmtop.core.models import Snapshot
from llmtop.core.rates import RateTracker
from llmtop.core.store import Store
from llmtop.providers.host import HostProvider
from llmtop.providers.nvidia import NvidiaProvider


class Runtime:
    def __init__(self, config: Config, demo: bool = False, client: httpx.AsyncClient | None = None):
        self.config = config
        self.demo = demo
        self.runtime_id = str(uuid.uuid4())
        self.sequence = 0
        self.store = Store(config.monitor.history_seconds, config.monitor.refresh_interval_seconds)
        self.client = client or httpx.AsyncClient(
            timeout=config.monitor.http_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(
                max_connections=config.monitor.max_concurrent_polls,
                max_keepalive_connections=config.monitor.max_concurrent_polls,
            ),
        )
        self.owns_client = client is None
        self.fetcher = Fetcher(self.client, config.monitor)
        self.rates = RateTracker(config.monitor.stale_after_seconds)
        self.adapters = [
            EngineAdapter(c, self.fetcher, self.rates) for c in config.services if c.enabled
        ]
        self.hosts = [HostProvider(h) for h in config.hosts]
        self.gpus = [] if demo else [NvidiaProvider(h) for h in config.hosts]
        self.gpu_pending: dict[int, asyncio.Future] = {}
        self.synthetic = Demo(config, self.adapters) if demo else None
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.ready = asyncio.Event()
        self.last_error: str | None = None

    async def poll(self) -> Snapshot:
        async with self.lock:
            if self.synthetic:
                services, hosts = self.synthetic.collect(time.monotonic())
            else:

                async def host_sample(index: int):
                    provider = self.hosts[index]
                    host = provider.collect()
                    devices, reason = await self.sample_gpu(index)
                    return host.model_copy(
                        update={"devices": devices, "reason": host.reason or reason}
                    )

                # One scheduler owns all IO. Requests and display clients only read this store.
                services, hosts = await asyncio.gather(
                    asyncio.gather(*(adapter.collect() for adapter in self.adapters)),
                    asyncio.gather(*(host_sample(i) for i in range(len(self.hosts)))),
                )
            self.sequence += 1
            snapshot = Snapshot(
                runtime_id=self.runtime_id,
                snapshot_seq=self.sequence,
                demo=self.demo,
                refresh_interval_seconds=self.config.monitor.refresh_interval_seconds,
                stale_after_seconds=self.config.monitor.stale_after_seconds,
                services=list(services),
                hosts=list(hosts),
            )
            self.store.publish(snapshot)
            self.last_error = None
            self.ready.set()
            return snapshot

    async def sample_gpu(self, index: int):
        loop = asyncio.get_running_loop()
        pending = self.gpu_pending.get(index)
        if pending is not None and not pending.done():
            return [], "GPU provider is still unavailable after timeout"
        if pending is None:
            pending = loop.create_future()
            self.gpu_pending[index] = pending

            def collect():
                try:
                    result = self.gpus[index].collect()
                except Exception:
                    result = ([], "GPU provider failed")
                if not loop.is_closed():
                    loop.call_soon_threadsafe(pending.set_result, result)

            # At most one outstanding job per provider; a stuck driver cannot stall
            # engine polling, accumulate threads, or prevent process shutdown.
            threading.Thread(target=collect, daemon=True, name="llmtop-gpu").start()
        try:
            result = await asyncio.wait_for(asyncio.shield(pending), timeout=3)
            self.gpu_pending.pop(index, None)
            return result
        except TimeoutError:
            return [], "GPU provider timed out"

    async def run(self) -> None:
        while True:
            started = time.monotonic()
            try:
                await self.poll()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.last_error = "Collector cycle failed; retrying"
                self.ready.set()
            await asyncio.sleep(
                max(
                    0.05,
                    self.config.monitor.refresh_interval_seconds - (time.monotonic() - started),
                )
            )

    async def start(self) -> None:
        if self.task is None:
            self.task = asyncio.create_task(self.run(), name="llmtop-collector")
        await asyncio.wait_for(
            self.ready.wait(), timeout=self.config.monitor.http_timeout_seconds * 3 + 5
        )

    async def close(self) -> None:
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        for index, gpu in enumerate(self.gpus):
            if index not in self.gpu_pending or self.gpu_pending[index].done():
                gpu.close()
        if self.owns_client:
            await self.client.aclose()
