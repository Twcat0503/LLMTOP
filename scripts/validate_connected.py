"""Verify a connected TUI against the same backend history used by Web."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from textual.widgets import DataTable

from llmtop.client import ConnectedClient
from llmtop.tui import MonitorApp


async def validate():
    client = ConnectedClient("http://127.0.0.1:8787")
    app = MonitorApp(connected=client, ascii_only=True)
    async with app.run_test(size=(120, 40)) as pilot:
        for _ in range(30):
            await pilot.pause(0.1)
            if app.displayed:
                break
        assert app.displayed is not None
        app.action_pause()
        snapshot = app.displayed
        service = next(s for s in snapshot.services if s.id == "atlas-vllm")
        row = app.query_one("#services", DataTable).get_row(service.id)
        async with httpx.AsyncClient() as reader:
            response = await reader.get(
                "http://127.0.0.1:8787/api/v1/history",
                params={"id": service.id, "metric": "output_tps"},
            )
        history = response.json()
        point = next(
            p for p in history["series"][0]["points"] if p["snapshot_seq"] == snapshot.snapshot_seq
        )
        assert history["runtime_id"] == snapshot.runtime_id
        assert point["value"] == service.metrics["output_tps"].value
        assert row[4] == f"{point['value']:,.1f}"
        result = {
            "status": "passed",
            "runtime_id": snapshot.runtime_id,
            "snapshot_seq": snapshot.snapshot_seq,
            "connected_tui_output_tps": row[4],
            "backend_history_output_tps": point["value"],
            "new_collector": False,
            "demo": snapshot.demo,
        }
    Path("artifacts/connected-tui.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(validate())
