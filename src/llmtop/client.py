from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import httpx

from llmtop.core.models import Snapshot


def decode_snapshot(data: str | bytes) -> Snapshot:
    value = json.loads(data)
    value.pop("metrics", None)  # Flattened read-only projection is rebuilt from entities.
    return Snapshot.model_validate(value)


class ConnectedClient:
    """Read a running collector; never contact engine endpoints."""

    def __init__(self, url: str, fallback_seconds: float = 2):
        self.url = url.rstrip("/")
        self.interval = fallback_seconds
        self.client = httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False)
        self.connection = "Reconnecting"
        self.latest: Snapshot | None = None

    async def updates(self) -> AsyncIterator[Snapshot]:
        cursor = None
        while True:
            try:
                response = await self.client.get(self.url + "/api/v1/snapshot")
                response.raise_for_status()
                snapshot = decode_snapshot(response.content)
                self.latest = snapshot
                self.connection = "Connected"
                yield snapshot
                headers = {"Last-Event-ID": cursor} if cursor else {}
                async with self.client.stream(
                    "GET",
                    self.url + "/api/v1/events",
                    headers=headers,
                    timeout=httpx.Timeout(5, read=15),
                ) as stream:
                    stream.raise_for_status()
                    kind, data, event_id = None, None, None
                    async for line in stream.aiter_lines():
                        if line.startswith("event: "):
                            kind = line[7:]
                        elif line.startswith("id: "):
                            event_id = line[4:]
                        elif line.startswith("data: "):
                            data = line[6:]
                        elif not line:
                            if kind == "snapshot" and data:
                                snapshot = decode_snapshot(data)
                                if (
                                    not self.latest
                                    or snapshot.runtime_id != self.latest.runtime_id
                                    or snapshot.snapshot_seq > self.latest.snapshot_seq
                                ):
                                    self.latest = snapshot
                                    self.connection = "Connected"
                                    yield snapshot
                                cursor = event_id
                            kind, data, event_id = None, None, None
            except (httpx.HTTPError, ValueError):
                self.connection = "Reconnecting"
            await asyncio.sleep(self.interval)

    async def close(self):
        await self.client.aclose()
