# Changelog

## 0.1.0 — unreleased alpha baseline

- Shared collector, snapshot/history, counter epochs and explicit missing-data status.
- vLLM and llama.cpp metric adapters; local host and optional NVIDIA providers.
- TUI, connected TUI, React Web, read-only REST/SSE, one-shot JSON and diagnostics.
- Default TUI launch, non-TTY guidance, persistent user configuration and `llmtop init`.
- `llmtop web`, browser launch after startup, headless URLs and SSH forwarding guidance.
- User wheel installer with isolated dependencies, persistent shell PATH setup and pre-activation checks.
- `llmtop update` and `llmtop rollback`: check a configured HTTPS release source (`[update].source_url`, verified against `SHA256SUMS`), activate a new environment atomically while keeping the previous version, and restore it on request.
- English primary README with a Traditional Chinese translation (`README.zh-TW.md`) and language links.
- MIT license, contribution guidance, public validation summary and source/package release audit.
- Local Git baseline with LF normalization and an explicit, evidence-based alpha publication checklist.

This baseline has not been published. Live llama.cpp and macOS gates remain open. Official release-source selection remains open; update checks ship without a built-in default and require an explicit `[update].source_url`.
