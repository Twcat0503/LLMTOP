**English** | [繁體中文](README.zh-TW.md)

<div align="center">

# LLMTOP

**A TUI and Web monitor for self-hosted LLM inference**

Tokens, throughput, queue depth, KV cache, and host hardware — vLLM, llama.cpp, and the machines they run on, in one read-only view.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![Version 0.1.0 alpha](https://img.shields.io/badge/version-0.1.0--alpha-orange)](CHANGELOG.md)
[![Platform Linux · macOS](https://img.shields.io/badge/platform-Linux%20%C2%B7%20macOS-lightgrey)](docs/SUPPORT-MATRIX.md)

</div>

> **Status:** 0.1.0 is an **unreleased alpha baseline**. vLLM on Linux and NVIDIA GPUs are hardware-verified; live llama.cpp and macOS gates are still open. Evidence: [public validation summary](docs/VALIDATION.md) · Plans: [roadmap](docs/ROADMAP.md).

## What is LLMTOP?

LLMTOP is a terminal (TUI) and web dashboard for self-hosted LLM inference services. It puts the engines you run — vLLM, llama.cpp — and the host hardware behind them in a single view: input/output tokens and tokens/sec, running/waiting requests, KV cache usage, CPU/RAM/swap, and NVIDIA device stats where available.

The TUI and the Web share one collector, one snapshot, and one history buffer, so both surfaces always show the same numbers. LLMTOP is read-only by default: it polls observability endpoints (`/metrics` and friends) and never sends inference requests.

## Why LLMTOP?

- **Missing data stays missing.** When a value cannot be known, LLMTOP shows `N/A` with its status and reason instead of guessing, zero-filling, or summing extra rank/replica series.
- **Read-only by design.** Monitoring never issues inference probes; credentials are read from server environment variables only and never sent to the browser.
- **One engine, two surfaces.** The TUI and the Web render the same snapshot — identical values, units, and missing-data reasons.
- **Restart-safe counters.** Counter epochs survive engine restarts, series changes, and long gaps; a failing GPU collector never stalls engine polling.
- **Remote-friendly.** The web backend binds loopback only, SSH forwarding guidance is built in, and the TUI can attach to a remote backend with `--connect`.

## Features

### Engine metrics

- Input/output token counters with live throughput (tokens/sec)
- Running/waiting request gauges where the engine exposes them
- KV cache usage from native engine ratios (llama.cpp context capacity is never reported as KV usage)
- Explicit metric selection: when a scrape contains multiple series you pick the labels — LLMTOP refuses to sum ranks or replicas

### Host & GPU

- CPU, RAM, swap, and process stats via psutil
- NVIDIA stats via NVML (optional extra), degrading to nvidia-smi or an explicit `N/A`
- Per-host data scoping: reading a remote engine URL never pretends to show remote hardware

### Interfaces

- TUI: search, sort, trend sparklines, pause, help; `--ascii` for plain terminals
- Web (React): filters, sorting, per-service detail, and trend charts fed only by backend history — gaps stay visible
- Scripting: `llmtop once --json` for one-shot snapshots; `llmtop schema` prints the snapshot JSON schema
- Live updates over SSE, with snapshot fallback on disconnect

### Deployment

- A single wheel bundles the built Web UI — no Node.js needed at runtime
- Isolated user installer (default `~/.local/share/llmtop`, command in `~/.local/bin`) with pre-activation checks; a failed install keeps the previous version
- Demo mode (`--demo`) renders synthetic data clearly labeled as such — no engine I/O

## Supported engines

| Engine | Status | What you get | Notes |
| --- | --- | --- | --- |
| vLLM (OpenAI server) | Verified on Linux | Token counters + t/s, running/waiting, native KV ratio via `/metrics` | Verified against vLLM 0.29.0 on Ubuntu 26.04 |
| llama.cpp server | Implemented, synthetic fixtures only | Token counters, processing/deferred gauges via `/metrics` | Requires `--metrics`; live-server gate open; context capacity is not KV usage |
| SGLang server | On the roadmap | — | Planned for M2 |
| Ollama | On the roadmap | — | Planned for M2 |

Per-version and per-platform claims live in the [support matrix](docs/SUPPORT-MATRIX.md): a combination is only marked verified after fixtures and real-hardware acceptance.

## Installation

Running LLMTOP needs Python 3.11+; building from source also needs Node 24 and uv. No official repository or package index is set up yet — install from a trusted source copy or build artifact.

```sh
uv sync --locked --extra dev
cd frontend
npm ci --no-audit --no-fund
npm run build
cd ..
uv build --wheel
python3 scripts/install_user.py \
  --wheel dist/llmtop-0.1.0-py3-none-any.whl \
  --ensure-path
```

The installer creates an isolated environment for Linux/macOS users, by default in `~/.local/share/llmtop`, and places the command in `~/.local/bin`. `--ensure-path` adds repeatable PATH setup for Bash/Zsh/POSIX sh; after reopening a login shell, the same version works from any directory. To use it immediately: `export PATH="$HOME/.local/bin:$PATH"`. An existing command of the same name, or a directory not managed by this tool, is never overwritten.

Use `--install-dir`/`--bin-dir` to relocate, `--gpu` to add the NVIDIA extra, `--constraints` for exported pinned dependencies, and `--wheelhouse` for offline installs. A new environment activates only after dependency, version, and schema checks pass. Official update checks are a later item.

## Quick start

```sh
llmtop init      # create a private config that watches local hardware only
llmtop doctor    # check config, endpoints, and permissions
llmtop           # open the TUI
```

Edit the config to add engines — see the [minimal](examples/llmtop.minimal.toml) and [full](examples/llmtop.example.toml) examples. Adjust `hardware_scope` for VMs and containers.

```toml
schema_version = 1

[[hosts]]
id = "local"
collector = "local"

[[services]]
id = "vllm"
host_id = "local"
engine = "vllm"
api_url = "http://127.0.0.1:8000"
```

Config precedence: `--config PATH` → `LLMTOP_CONFIG` → user config → legacy `llmtop.toml` in the working directory. An explicitly named file that does not exist is an error — never a silent fallback.

| Platform | User configuration |
| --- | --- |
| Linux | `${XDG_CONFIG_HOME:-$HOME/.config}/llmtop/llmtop.toml`; the XDG path must be absolute |
| macOS | `~/Library/Application Support/llmtop/llmtop.toml` |

Prefer a preview first? `llmtop --demo` renders synthetic data clearly labeled "Demo data". On a non-interactive terminal, the bare command suggests `once` or Web instead.

## Web & remote monitoring

```sh
llmtop web               # alias of serve; local desktops open the browser after startup
llmtop serve --no-open   # headless: prints the URL and SSH forwarding guidance only
```

The backend stays on loopback, by default [http://127.0.0.1:8787](http://127.0.0.1:8787). From your workstation, create a tunnel — replace `YOUR_SSH_ALIAS` with your own SSH alias:

```sh
ssh -N -L 127.0.0.1:8787:127.0.0.1:8787 YOUR_SSH_ALIAS
```

You can also skip the browser and attach the TUI to the backend; connected mode reads only the backend URL and never loads engine credentials:

```sh
llmtop tui --connect http://127.0.0.1:8787
```

## CLI reference

| Command | Description |
| --- | --- |
| `llmtop` | TUI (default) |
| `llmtop once` | Two samples by default to compute throughput; `--json` for machine-readable output; with `--samples 1` rates report warming_up |
| `llmtop doctor` | Diagnose config and endpoints |
| `llmtop init` | Create the user config; `--print` writes the template to stdout |
| `llmtop web` / `llmtop serve` | Web backend; `--port` to change the port; `--open`/`--no-open` to control the browser |
| `llmtop tui --connect URL` | TUI attached to an existing backend |
| `llmtop schema` | Print the snapshot JSON schema |

Global flags: `--config`, `--demo`, `--ascii`, `--theme dark|light|auto`, `--version`.

TUI keys: `q` quit · `/` search · `Esc` back · `s` sort · `t` toggle trend · `space` pause · `?` help.

## How it works

```text
engines (read-only /metrics) ─┐
hosts (psutil · NVML)         ├─▶ collectors ─▶ snapshot + history ─┬─▶ TUI
                                                                    ├─▶ Web UI (REST + SSE)
                                                                    └─▶ once --json
```

- Adapters select explicit Prometheus label sets and reject unselected multi-series scrapes, so ranks and replicas are never summed
- Counter epochs handle restarts, series changes, and long gaps
- REST API: `/health`, `/api/v1/snapshot`, `/api/v1/capabilities`, `/api/v1/history`, `/api/v1/events` (SSE)

Details: [architecture](docs/ARCHITECTURE.md), [interfaces](docs/INTERFACES.md), [metric spec](docs/METRIC-SPEC.md).

## Privacy & security

- Read-only monitoring by default — no inference requests
- Credentials are read from server environment variables only and never sent to the browser
- No telemetry, nothing phones home
- The web backend binds loopback only

Current scope is service-level running/waiting counts — there is no full per-request lifecycle or source ranking yet. Remote engine HTTP does not imply remote hardware: without a collector on that host, values stay explicitly `N/A`. Report suspected vulnerabilities per [SECURITY](SECURITY.md).

## Project status

Verified: vLLM 0.29.0 and NVIDIA NVML on real Linux hardware (Ubuntu 26.04), 71 pytest and 6 Chromium tests, and the install/release audit flow. Still open: live llama.cpp, macOS/Apple GPU, sustained non-zero load, public CI, and an official release. Live status: [TODO](docs/TODO.md) and [validation record](docs/VALIDATION.md).

Existing install artifacts are historical validation products only; an official release must be rebuilt from a confirmed commit.

## Documentation

| Document | Contents |
| --- | --- |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Overall architecture and data flow |
| [METRIC-SPEC](docs/METRIC-SPEC.md) | Metric semantics and unit contract |
| [INTERFACES](docs/INTERFACES.md) | REST/SSE interface definitions |
| [SUPPORT-MATRIX](docs/SUPPORT-MATRIX.md) | Engine/OS/hardware support verification |
| [VALIDATION](docs/VALIDATION.md) | Public validation summary and evidence |
| [ROADMAP](docs/ROADMAP.md) · [PROJECT-PLAN](docs/PROJECT-PLAN.md) · [TODO](docs/TODO.md) | Plans and current progress |
| [RELEASING](docs/RELEASING.md) | Release procedure and artifact audit |

## Contributing

The project is in alpha. Development setup, checks, and contribution rules are in [CONTRIBUTING](CONTRIBUTING.md); read the [roadmap](docs/ROADMAP.md) and [metric semantics](docs/METRIC-SPEC.md) before changing a collector or adapter.

## License

Released under the [MIT](LICENSE) license. Third-party dependencies retain their own licenses.
