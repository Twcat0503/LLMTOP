from __future__ import annotations

import asyncio
from contextlib import suppress

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Select, Static, TabbedContent, TabPane

from llmtop.client import ConnectedClient
from llmtop.core.models import Snapshot, Status, utc_now
from llmtop.core.runtime import Runtime
from llmtop.presentation import gib, number, sparkline


class Detail(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close")]
    DEFAULT_CSS = "Detail {align: center middle;} #detail {width: 90%; height: 85%; border: solid #53d9bf; background: #111820; padding: 1 2;}"

    def __init__(self, text: str):
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="detail"):
            yield Static(Text(self.text))


class MonitorApp(App):
    TITLE = "LLMTOP"
    CSS = """
    Screen {background: #0b1016; color: #e7edf4;}
    #summary {height: 3; padding: 1; color: #53d9bf;}
    #filters {height: 3;}
    #search {width: 1fr;}
    Select {width: 22;}
    DataTable {height: 1fr; background: #111820;}
    TabbedContent {height: 1fr;}
    ContentSwitcher {height: 1fr;}
    TabPane {height: 1fr; padding: 0;}
    #trend {height: 4; padding: 1;}
    #status {height: 2; padding: 0 1; color: #8d9bad;}
    Screen.light {background: #f5f7f9; color: #172b36;}
    Screen.light DataTable {background: #ffffff;}
    Screen.light #summary {color: #07866d;}
    Screen.light #status {color: #4b5b6e;}
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("space", "pause", "Pause"),
        Binding("/", "search", "Search"),
        Binding("s", "sort", "Sort"),
        Binding("t", "trend", "Trend"),
        Binding("escape", "focus_table", "Table"),
        Binding("?", "help", "Help"),
    ]

    def __init__(
        self,
        runtime: Runtime | None = None,
        connected: ConnectedClient | None = None,
        ascii_only: bool = False,
        theme: str = "auto",
    ):
        super().__init__()
        self.runtime = runtime
        self.connected = connected
        self.ascii_only = ascii_only
        self.latest: Snapshot | None = None
        self.displayed: Snapshot | None = None
        self.paused = False
        self.sort_output = False
        self.reader: asyncio.Task | None = None
        self.history: dict[str, dict[str, list[float | None]]] = {}
        self.frozen_history: dict[str, dict[str, list[float | None]]] = {}
        self.trend_metrics = [
            "output_tps",
            "input_tps",
            "kv_cache_usage_ratio",
            "engine_waiting_requests",
        ]
        self.trend_index = 0
        self.seen: tuple[str, int] | None = None
        if theme == "light":
            self.theme = "textual-light"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Collector is initializing…", id="summary")
        with Horizontal(id="filters"):
            yield Input(placeholder="Search services…", id="search")
            yield Select(
                [
                    ("All engines", "all"),
                    ("vLLM", "vllm"),
                    ("llama.cpp", "llamacpp"),
                    ("Strata", "strata"),
                ],
                value="all",
                allow_blank=False,
                id="engine",
            )
            hosts = self.runtime.config.hosts if self.runtime else []
            yield Select(
                [("All hosts", "all"), *[(h.label, h.id) for h in hosts]],
                value="all",
                allow_blank=False,
                id="host",
            )
        with TabbedContent():
            with TabPane("Services", id="services-pane"):
                yield DataTable(id="services", cursor_type="row", zebra_stripes=True)
                yield Static("N/A", id="trend")
            with TabPane("Hosts", id="hosts-pane"):
                yield DataTable(id="hosts", cursor_type="row", zebra_stripes=True)
        yield Static(
            "Missing metrics are shown as N/A. Remote hardware requires a collector on that host.",
            id="status",
        )
        yield Footer()

    async def on_mount(self):
        if self.theme == "textual-light":
            self.screen.add_class("light")
        self.query_one("#services", DataTable).add_columns(
            "Service",
            "Engine / model",
            "Status",
            "Input t/s",
            "Output t/s",
            "Running",
            "Waiting",
            "KV",
        )
        self.query_one("#hosts", DataTable).add_columns(
            "Host / device", "Scope", "CPU / GPU", "RAM / VRAM", "Swap / extra"
        )
        if self.runtime:
            await self.runtime.start()
        if self.connected:
            self.reader = asyncio.create_task(self.read_connected())
        self.set_interval(0.5, self.refresh_snapshot)
        self.query_one("#services", DataTable).focus()

    async def read_connected(self):
        async for snapshot in self.connected.updates():
            self.latest = snapshot

    def refresh_snapshot(self):
        if self.runtime:
            self.latest = self.runtime.store.current
        if self.latest is None:
            return
        key = (self.latest.runtime_id, self.latest.snapshot_seq)
        if key != self.seen:
            if self.seen and key[0] != self.seen[0]:
                self.history.clear()
            for service in self.latest.services:
                series = self.history.setdefault(service.id, {})
                for metric in self.trend_metrics:
                    value = service.metrics.get(metric)
                    points = series.setdefault(metric, [])
                    points.append(value.value if value and value.status == Status.OK else None)
                    del points[:-40]
            self.seen = key
        if not self.paused:
            self.displayed = self.latest
            self.frozen_history = {
                i: {m: list(v) for m, v in series.items()} for i, series in self.history.items()
            }
        if self.connected:
            host_select = self.query_one("#host", Select)
            inventory = tuple(h.id for h in self.latest.hosts)
            if inventory != getattr(self, "host_inventory", None):
                host_select.set_options(
                    [("All hosts", "all"), *[(h.label, h.id) for h in self.latest.hosts]]
                )
                host_select.value = "all"
                self.host_inventory = inventory
        self.render_snapshot()

    def render_snapshot(self):
        snap = self.displayed
        if snap is None:
            return
        search = self.query_one("#search", Input).value.casefold()
        engine = self.query_one("#engine", Select).value
        host = self.query_one("#host", Select).value
        services = [
            s
            for s in snap.services
            if (engine == "all" or s.engine == engine)
            and (host == "all" or s.host_id == host)
            and search in f"{s.label} {s.model_name or ''}".casefold()
        ]
        if self.sort_output:
            services.sort(
                key=lambda s: (
                    s.metrics["output_tps"].value
                    if s.metrics.get("output_tps") and s.metrics["output_tps"].value is not None
                    else -1
                ),
                reverse=True,
            )
        else:
            services.sort(key=lambda s: s.label)
        table = self.query_one("#services", DataTable)
        old_row = table.cursor_row
        table.clear()
        for service in services:
            m = service.metrics
            table.add_row(
                service.label,
                f"{service.engine} / {service.model_name or 'N/A'}",
                service.health.value,
                number(m.get("input_tps")),
                number(m.get("output_tps")),
                number(m.get("engine_running_requests")),
                number(m.get("engine_waiting_requests")),
                number(m.get("kv_cache_usage_ratio"), ratio=True),
                key=service.id,
            )
        if services:
            table.move_cursor(row=min(old_row, len(services) - 1))
        hardware = self.query_one("#hosts", DataTable)
        hardware.clear()
        for item in snap.hosts:
            if host != "all" and host != item.id:
                continue
            m = item.metrics
            total, available = m.get("host_ram_total_bytes"), m.get("host_ram_available_bytes")
            used = (
                f"{(total.value - available.value) / 1073741824:.1f} GiB"
                if total and available and total.value is not None and available.value is not None
                else "N/A"
            )
            hardware.add_row(
                item.label,
                item.scope,
                number(m.get("host_cpu_usage_ratio"), ratio=True),
                used + " / " + gib(total),
                gib(m.get("host_swap_used_bytes")),
                key=item.id,
            )
            for device in item.devices:
                g = device.metrics
                hardware.add_row(
                    device.label,
                    "device",
                    number(g.get("gpu_utilization_ratio"), ratio=True),
                    gib(g.get("gpu_memory_used_bytes"))
                    + " / "
                    + gib(g.get("gpu_memory_total_bytes")),
                    number(g.get("gpu_temperature_celsius")) + " °C",
                    key=device.id,
                )
        age = (utc_now() - snap.collected_at).total_seconds()
        connection = self.connected.connection if self.connected else "Connected"
        stale_after = snap.stale_after_seconds
        stale = " · stale" if age > stale_after and not self.paused else ""
        self.query_one("#summary", Static).update(
            Text(
                f"{'Demo data · ' if snap.demo else ''}{connection}{stale} · {'Paused · ' if self.paused else ''}seq {snap.snapshot_seq} · {len(services)} services · {snap.collected_at.astimezone().strftime('%H:%M:%S')}"
            )
        )
        metric = self.trend_metrics[self.trend_index]
        selected = services[min(table.cursor_row, len(services) - 1)] if services else None
        trend = (
            f"{selected.label} {sparkline(self.frozen_history.get(selected.id, {}).get(metric, []), self.ascii_only)}"
            if selected
            else "N/A"
        )
        self.query_one("#trend", Static).update(Text(metric + "  " + trend))

    def on_input_changed(self, event: Input.Changed):
        self.render_snapshot()

    def on_select_changed(self, event: Select.Changed):
        if self.displayed:
            self.render_snapshot()

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        if not self.displayed:
            return
        identity = event.row_key.value
        entity = next(
            (s for s in [*self.displayed.services, *self.displayed.hosts] if s.id == identity), None
        )
        if entity is None:
            entity = next(
                (d for h in self.displayed.hosts for d in h.devices if d.id == identity), None
            )
        if entity:
            lines = [entity.label, getattr(entity, "reason", None) or "", ""]
            for metric in entity.metrics.values():
                lines.append(
                    f"{metric.metric}: {number(metric)} {metric.unit} [{metric.status.value}]\n  source={metric.source_metric or 'N/A'} scope={metric.scope} window={metric.window_seconds} epoch={metric.epoch}\n  {metric.reason or ''}"
                )
            self.push_screen(Detail("\n".join(lines)))

    def action_pause(self):
        self.paused = not self.paused
        self.refresh_snapshot()

    def action_search(self):
        self.query_one("#search", Input).focus()

    def action_focus_table(self):
        self.query_one("#services", DataTable).focus()

    def action_sort(self):
        self.sort_output = not self.sort_output
        self.render_snapshot()

    def action_trend(self):
        self.trend_index = (self.trend_index + 1) % len(self.trend_metrics)
        self.render_snapshot()

    def action_help(self):
        self.push_screen(
            Detail(
                "LLMTOP\n\nq: quit · space: pause display · /: search · s: sort output throughput\nTab: move focus · arrows: select · Enter: details · Escape: close\n\nCollector continues while paused. Connected mode reads the existing backend.\nN/A retains its status and reason; rates need two samples.\nDemo data is synthetic. No inference requests are sent."
            )
        )

    async def on_unmount(self):
        if self.reader:
            self.reader.cancel()
            with suppress(asyncio.CancelledError):
                await self.reader
        if self.connected:
            await self.connected.close()
        if self.runtime:
            await self.runtime.close()
