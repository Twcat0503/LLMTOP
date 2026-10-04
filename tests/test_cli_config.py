import io
import os
import tomllib
from pathlib import Path

import pytest
from rich.console import Console

from llmtop import cli
from llmtop.config import (
    Config,
    ConfigError,
    config_template,
    init_config,
    load_config,
    resolve_config_path,
    user_config_path,
)
from llmtop.web_launch import WebServer, desktop_available, web_url


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("LLMTOP_CONFIG", raising=False)
    monkeypatch.setattr("llmtop.config.user_config_path", lambda: tmp_path / "settings/llmtop.toml")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_config_precedence_and_missing_override(isolated_config, monkeypatch):
    legacy = isolated_config / "llmtop.toml"
    legacy.write_text(config_template())
    assert resolve_config_path() == legacy
    user = init_config()
    assert resolve_config_path() == user
    alternate = isolated_config / "alternate.toml"
    alternate.write_text(config_template())
    monkeypatch.setenv("LLMTOP_CONFIG", str(alternate))
    assert resolve_config_path() == alternate
    assert resolve_config_path(legacy) == legacy
    missing = isolated_config / "missing.toml"
    with pytest.raises(ConfigError, match="Unable to read"):
        load_config(missing)
    monkeypatch.setenv("LLMTOP_CONFIG", str(missing))
    with pytest.raises(ConfigError, match="LLMTOP_CONFIG"):
        load_config()


def test_user_config_is_independent_of_cwd(isolated_config, monkeypatch):
    original = init_config()
    directory = isolated_config / "another-directory"
    directory.mkdir()
    monkeypatch.chdir(directory)
    assert resolve_config_path() == original
    assert load_config().services == []


def test_init_is_private_and_never_overwrites(isolated_config):
    target = init_config()
    original = target.read_bytes()
    assert load_config(target).hosts[0].collector == "local"
    assert not load_config(target).services
    if os.name == "posix":
        assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ConfigError, match="already exists"):
        init_config()
    assert target.read_bytes() == original


def test_init_honors_environment_and_print_has_no_side_effects(
    isolated_config, monkeypatch, capsys
):
    target = isolated_config / "env.toml"
    monkeypatch.setenv("LLMTOP_CONFIG", str(target))
    assert cli.main(["init", "--print"]) == 0
    assert Config.model_validate(tomllib.loads(capsys.readouterr().out)).services == []
    assert not target.exists()
    assert cli.main(["init"]) == 0
    assert target.is_file()
    assert cli.main(["init"]) == 2


def test_xdg_relative_value_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr("llmtop.config.sys.platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative")
    assert user_config_path() == tmp_path / ".config/llmtop/llmtop.toml"


@pytest.mark.parametrize("arguments", [[], ["--demo"], ["tui", "--demo"]])
def test_non_tty_gives_actionable_commands(arguments, monkeypatch, capsys):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli, "load_config", lambda _: pytest.fail("Non-TTY must not load config"))
    assert cli.main(arguments) == 2
    output = capsys.readouterr().err
    assert "interactive terminal" in output
    assert "once --json" in output and "web --no-open" in output


def test_bare_connect_enters_tui_without_config(monkeypatch):
    captured = {}

    class App:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            captured["ran"] = True

    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("llmtop.tui.MonitorApp", App)
    monkeypatch.setattr(
        cli, "load_config", lambda _: pytest.fail("Connected TUI must not load config")
    )
    assert cli.main(["--connect", "http://127.0.0.1:8787", "--ascii"]) == 0
    assert captured["ran"] and captured["ascii_only"]
    assert captured["connected"].url == "http://127.0.0.1:8787"


@pytest.mark.parametrize(
    "command,options,opens",
    [
        ("web", [], True),
        ("web", ["--no-open"], False),
        ("serve", [], False),
        ("serve", ["--open"], True),
    ],
)
def test_web_alias_and_browser_policy(command, options, opens, monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "Runtime", lambda config, demo: (config, demo))
    monkeypatch.setattr(
        "llmtop.web_launch.serve",
        lambda runtime, **kwargs: captured.update(runtime=runtime, **kwargs),
    )
    assert cli.main([command, "--demo", "--port", "9876", *options]) == 0
    assert captured["open_browser"] is opens
    assert captured["runtime"][0].web.port == 9876
    assert captured["runtime"][1]


def test_invalid_web_port_never_starts(monkeypatch):
    monkeypatch.setattr(
        "llmtop.web_launch.serve", lambda *a, **kw: pytest.fail("Invalid port started")
    )
    assert cli.main(["web", "--demo", "--port", "0"]) == 2


def test_options_before_and_after_command():
    root = cli.parser()
    assert root.parse_args(["--demo", "once", "--json"]).demo
    assert root.parse_args(["tui", "--ascii", "--theme", "light"]).theme == "light"
    assert root.parse_args(["--config", "a.toml", "doctor"]).config == Path("a.toml")
    assert root.parse_args(["--config", "a.toml", "doctor", "--config", "b.toml"]).config == Path(
        "b.toml"
    )


def test_ssh_is_headless_even_with_display(monkeypatch):
    monkeypatch.setenv("SSH_CONNECTION", "example")
    monkeypatch.setenv("DISPLAY", ":1")
    assert not desktop_available()
    assert web_url("::1", 8787) == "http://[::1]:8787"


async def test_browser_only_runs_after_successful_startup(monkeypatch):
    import uvicorn

    started = []
    output = io.StringIO()

    async def successful(server, sockets):
        server.started = True
        started.append("server")

    monkeypatch.setattr(uvicorn.Server, "startup", successful)
    monkeypatch.setattr("llmtop.web_launch.desktop_available", lambda: True)
    monkeypatch.setattr(
        "llmtop.web_launch.webbrowser.open", lambda *a, **kw: started.append("browser") or False
    )
    server = WebServer(
        uvicorn.Config("unused:app"), open_browser=True, console=Console(file=output)
    )
    await server.startup()
    await server.browser_task
    assert started == ["server", "browser"]
    assert "manually" in output.getvalue()


async def test_headless_prints_forwarding_without_opening(monkeypatch):
    import uvicorn

    async def successful(server, sockets):
        server.started = True

    monkeypatch.setattr(uvicorn.Server, "startup", successful)
    monkeypatch.setattr("llmtop.web_launch.desktop_available", lambda: False)
    monkeypatch.setattr(
        "llmtop.web_launch.webbrowser.open", lambda *a, **kw: pytest.fail("Headless browser opened")
    )
    output = io.StringIO()
    server = WebServer(
        uvicorn.Config("unused:app", host="::1", port=9876),
        open_browser=True,
        console=Console(file=output, width=160),
    )
    await server.startup()
    assert "http://[::1]:9876" in output.getvalue()
    assert "127.0.0.1:9876:[::1]:9876 YOUR_SSH_ALIAS" in output.getvalue()
    assert server.browser_task is None


async def test_unsuccessful_startup_never_opens_browser(monkeypatch):
    import uvicorn

    async def unsuccessful(server, sockets):
        server.started = False

    monkeypatch.setattr(uvicorn.Server, "startup", unsuccessful)
    monkeypatch.setattr("llmtop.web_launch.desktop_available", lambda: True)
    monkeypatch.setattr(
        "llmtop.web_launch.webbrowser.open", lambda *a, **kw: pytest.fail("Unstarted browser")
    )
    output = io.StringIO()
    server = WebServer(
        uvicorn.Config("unused:app"), open_browser=True, console=Console(file=output)
    )
    await server.startup()
    assert not output.getvalue() and server.browser_task is None
