from __future__ import annotations

import asyncio
import os
import sys
import webbrowser

import uvicorn
from rich.console import Console

from llmtop.api import create_app
from llmtop.core.runtime import Runtime


def desktop_available() -> bool:
    if any(os.environ.get(name) for name in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")):
        return False
    return sys.platform in {"darwin", "win32"} or bool(
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )


def web_url(host: str, port: int) -> str:
    return f"http://{'[::1]' if host == '::1' else host}:{port}"


class WebServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, *, open_browser: bool, console: Console):
        super().__init__(config)
        self.open_browser = open_browser
        self.console = console
        self.browser_task: asyncio.Task | None = None

    async def startup(self, sockets=None) -> None:
        await super().startup(sockets)
        if not self.started:
            return
        url = web_url(self.config.host, self.config.port)
        self.console.print(f"LLMTOP Web: {url}", markup=False)
        if not desktop_available():
            self.console.print("SSH/headless: open the URL on a local browser after forwarding:")
            destination = "[::1]" if self.config.host == "::1" else self.config.host
            self.console.print(
                f"  ssh -N -L 127.0.0.1:{self.config.port}:{destination}:{self.config.port} "
                "YOUR_SSH_ALIAS",
                markup=False,
            )
            self.console.print(f"  Browser: http://127.0.0.1:{self.config.port}", markup=False)
        elif self.open_browser:
            self.browser_task = asyncio.create_task(self.launch_browser(url))

    async def launch_browser(self, url: str) -> None:
        try:
            opened = await asyncio.to_thread(webbrowser.open, url, new=2)
        except (OSError, webbrowser.Error):
            opened = False
        if not opened:
            self.console.print("Could not open a browser automatically; open the Web URL manually.")


def serve(runtime: Runtime, *, open_browser: bool, console: Console) -> None:
    settings = runtime.config.web
    server = WebServer(
        uvicorn.Config(
            create_app(runtime),
            host=settings.bind_host,
            port=settings.port,
            log_level="warning",
            access_log=False,
        ),
        open_browser=open_browser,
        console=console,
    )
    server.run()
