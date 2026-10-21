from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from llmtop import __version__
from llmtop.config import (
    ConfigError,
    config_template,
    demo_config,
    init_config,
    load_config,
    resolve_config_path,
)
from llmtop.core.models import Snapshot
from llmtop.core.runtime import Runtime
from llmtop.presentation import number


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="LLMTOP: shared LLM service and host monitor; defaults to TUI",
        epilog="Start with llmtop init. Use llmtop --demo for explicit synthetic data.",
    )
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--config", type=Path, help="Override LLMTOP_CONFIG and user configuration")
    root.add_argument("--demo", action="store_true", help="Explicit synthetic data; no engine IO")
    root.add_argument("--connect", help="Read an existing LLMTOP backend in TUI mode")
    root.add_argument("--ascii", action="store_true")
    root.add_argument("--theme", choices=("auto", "dark", "light"), default="auto")
    commands = root.add_subparsers(dest="command")
    for command in ("once", "doctor", "serve", "tui"):
        item = commands.add_parser(command, aliases=["web"] if command == "serve" else [])
        item.add_argument("--config", type=Path, default=argparse.SUPPRESS)
        item.add_argument(
            "--demo",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Explicit synthetic example data; no engine IO",
        )
        if command == "once":
            item.add_argument("--json", action="store_true")
            item.add_argument(
                "--samples",
                type=int,
                choices=(1, 2),
                default=2,
                help="Two samples are required for throughput",
            )
        elif command == "serve":
            item.add_argument("--port", type=int)
            browser = item.add_mutually_exclusive_group()
            browser.add_argument(
                "--open", "--open-browser", dest="open_browser", action="store_true"
            )
            browser.add_argument("--no-open", dest="open_browser", action="store_false")
            item.set_defaults(open_browser=None)
        elif command == "tui":
            item.add_argument(
                "--connect",
                default=argparse.SUPPRESS,
                help="Read an existing LLMTOP backend without engine polling",
            )
            item.add_argument("--ascii", action="store_true", default=argparse.SUPPRESS)
            item.add_argument(
                "--theme", choices=("auto", "dark", "light"), default=argparse.SUPPRESS
            )
    initialize = commands.add_parser("init", help="Create a private user configuration")
    initialize.add_argument("--config", type=Path, default=argparse.SUPPRESS)
    initialize.add_argument("--print", dest="print_template", action="store_true")
    commands.add_parser("schema")
    update = commands.add_parser(
        "update", help="Check for or install an update in a managed user install"
    )
    update.add_argument("--check", action="store_true", help="Report the latest version only")
    update.add_argument(
        "--wheel", type=Path, help="Install this wheel instead of using the update source"
    )
    commands.add_parser("rollback", help="Switch a managed install back to the previous version")
    return root


def run_update(args, console: Console) -> int:
    from llmtop.installer import InstallError
    from llmtop.update import (
        UpdateError,
        check_for_update,
        detect_install_root,
        rollback,
        update_from_source,
        update_from_wheel,
    )

    try:
        root = detect_install_root()
        if root is None:
            console.print(
                "This LLMTOP runtime is not a managed user install; update it with the "
                "installer you used or through your package manager.",
                style="red",
            )
            return 2
        if args.command == "rollback":
            receipt = rollback(root)
            console.print(
                f"Rolled back to LLMTOP {receipt['version']}. Restart llmtop to use it.",
                markup=False,
            )
            return 0
        if args.wheel is not None:
            receipt = update_from_wheel(root, args.wheel)
            console.print(
                f"Updated LLMTOP to {receipt['version']}. Restart llmtop to use it.",
                markup=False,
            )
            return 0
        config = load_config(args.config)
        if not config.update.source_url:
            console.print(
                "No update source is configured. Set [update].source_url in the configuration "
                "or install a wheel with llmtop update --wheel.",
                style="yellow",
                markup=False,
            )
            return 2
        result = check_for_update(config.update.source_url, config.update.allow_prerelease)
        console.print(f"Current: {result.current}", markup=False)
        if result.latest is None:
            console.print("Update source lists no LLMTOP release.", style="yellow", markup=False)
            return 2
        console.print(f"Latest:  {result.latest}", markup=False)
        if not result.newer:
            console.print("This install is up to date.")
            return 0
        if args.check:
            console.print("Run llmtop update to install it.")
            return 0
        receipt = update_from_source(root, config.update.source_url, config.update.allow_prerelease)
        if receipt is None:
            console.print("This install is up to date.")
        else:
            console.print(
                f"Updated LLMTOP to {receipt['version']}. Restart llmtop to use it.",
                markup=False,
            )
        return 0
    except (UpdateError, InstallError) as exc:
        console.print(str(exc), style="red", markup=False)
        return 2
    except ConfigError:
        console.print(
            "Unable to read the configuration. Run llmtop init, or select a file with --config.",
            style="red",
            markup=False,
        )
        return 2
    except (OSError, ValueError):
        # Keep detailed tool output in the private installation log.
        console.print(
            "LLMTOP could not update; check the update source, wheel and installation.log",
            style="red",
            markup=False,
        )
        return 2


async def once(config, demo: bool, samples: int) -> Snapshot:
    runtime = Runtime(config, demo)
    try:
        snapshot = await runtime.poll()
        if samples == 2:
            await asyncio.sleep(config.monitor.refresh_interval_seconds)
            snapshot = await runtime.poll()
        return snapshot
    finally:
        await runtime.close()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    console = Console(stderr=True)
    args.command = args.command or "tui"
    if args.command == "schema":
        print(json.dumps(Snapshot.model_json_schema(mode="serialization"), indent=2))
        return 0
    if args.command in {"update", "rollback"}:
        return run_update(args, console)
    try:
        if args.command == "init":
            if args.print_template:
                print(config_template(), end="")
            else:
                path = init_config(args.config)
                console.print(f"Created configuration: {path}", markup=False)
                console.print(
                    "Host monitoring is ready. Edit the file to add your engine endpoints."
                )
                console.print("Next: llmtop doctor, llmtop, or llmtop web")
            return 0
        if args.command == "tui" and not (sys.stdin.isatty() and sys.stdout.isatty()):
            console.print("TUI requires an interactive terminal.", style="red")
            console.print("Use llmtop once --json for output, or llmtop web --no-open for Web.")
            console.print("For synthetic examples, add --demo to either command.")
            return 2
        # Connected mode needs only the backend URL; never loads engine credentials.
        if args.command == "tui" and args.connect:
            from llmtop.client import ConnectedClient
            from llmtop.tui import MonitorApp

            MonitorApp(
                connected=ConnectedClient(args.connect), ascii_only=args.ascii, theme=args.theme
            ).run()
            return 0
        config = demo_config() if args.demo else load_config(args.config)
        if args.command in {"serve", "web"}:
            from llmtop.web_launch import serve

            if args.port is not None:
                web = config.web.model_copy(update={"port": args.port})
                config = type(config).model_validate(
                    {**config.model_dump(), "web": web.model_dump()}
                )
            serve(
                Runtime(config, args.demo),
                open_browser=(args.command == "web")
                if args.open_browser is None
                else args.open_browser,
                console=console,
            )
        elif args.command == "tui":
            from llmtop.client import ConnectedClient
            from llmtop.tui import MonitorApp

            connected = ConnectedClient(config.tui.connect_url) if config.tui.connect_url else None
            MonitorApp(
                runtime=None if connected else Runtime(config, args.demo),
                connected=connected,
                ascii_only=args.ascii or config.tui.ascii,
                theme=config.tui.theme if args.theme == "auto" else args.theme,
            ).run()
        else:
            snapshot = asyncio.run(
                once(config, args.demo, args.samples if args.command == "once" else 1)
            )
            if args.command == "doctor":
                print(
                    json.dumps(
                        {
                            "version": __version__,
                            "python": platform.python_version(),
                            "platform": platform.system(),
                            "demo": snapshot.demo,
                            "config_path": None
                            if args.demo
                            else str(resolve_config_path(args.config)),
                            "services": [
                                {
                                    "id": s.id,
                                    "engine": s.engine,
                                    "health": s.health,
                                    "reason": s.reason,
                                    "engine_version": s.engine_version,
                                    "capabilities": [c.model_dump() for c in s.capabilities],
                                }
                                for s in snapshot.services
                            ],
                            "hosts": [
                                {
                                    "id": h.id,
                                    "scope": h.scope,
                                    "reason": h.reason,
                                    "devices": [
                                        {
                                            "id": d.id,
                                            "label": d.label,
                                            "provider": d.provider,
                                            "driver_version": d.driver_version,
                                        }
                                        for d in h.devices
                                    ],
                                }
                                for h in snapshot.hosts
                            ],
                        },
                        indent=2,
                    )
                )
            elif args.json:
                print(snapshot.model_dump_json())
            else:
                table = Table(title="LLMTOP" + (" · Demo data" if snapshot.demo else ""))
                for label in (
                    "Service",
                    "Engine",
                    "Status",
                    "Input t/s",
                    "Output t/s",
                    "Running",
                    "Waiting",
                    "KV",
                ):
                    table.add_column(label)
                for service in snapshot.services:
                    m = service.metrics
                    table.add_row(
                        service.label,
                        service.engine,
                        service.health,
                        number(m.get("input_tps")),
                        number(m.get("output_tps")),
                        number(m.get("engine_running_requests")),
                        number(m.get("engine_waiting_requests")),
                        number(m.get("kv_cache_usage_ratio"), ratio=True),
                    )
                Console().print(table)
    except (ConfigError, OSError, ValueError) as exc:
        # Configuration errors are sanitized by the loader; no raw endpoints or credentials.
        console.print(
            str(exc)
            if isinstance(exc, ConfigError)
            else "LLMTOP could not start; check configuration and local resources",
            style="red",
            markup=False,
        )
        return 2
    except KeyboardInterrupt:
        return 130
    return 0
