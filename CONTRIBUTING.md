# Contributing

LLMTOP is an alpha project. Start with [the roadmap](docs/ROADMAP.md) and [metric semantics](docs/METRIC-SPEC.md) before changing a collector or adapter. TUI and Web changes must preserve the same snapshot values, units, missing data and quality reasons.

## Development

Use Python 3.11+ and Node 24. Keep `uv.lock` and `frontend/package-lock.json` in sync with dependency changes.

```sh
uv sync --locked --extra dev
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q
cd frontend
npm ci --no-audit --no-fund
npm run build
cd ..
uv run python scripts/check_release.py
```

Browser tests require a running `llmtop serve --demo` and Playwright Chromium. See [the release procedure](docs/RELEASING.md) for complete artifact verification.

## Changes and reports

Explain the problem, resulting behavior and relevant validation. New engine support needs a fixed upstream version, synthetic or sanitized fixtures, and separate evidence for real hardware. A Linux CPU test does not establish macOS or GPU support. Do not send inference requests as a default monitoring probe.

Only contribute code and assets that you have the right to distribute under the [MIT license](LICENSE). Third-party dependencies retain their own licenses. Never include real endpoint inventories, credentials, request content, raw telemetry or workstation instructions in a patch, issue or screenshot. Local settings and internal reports are excluded by Git and packaging rules; use the release audit before staging a contribution.

For a suspected vulnerability, follow [SECURITY.md](SECURITY.md).
