from __future__ import annotations

import os
import sys
import tomllib
from importlib.resources import files
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ConfigError(ValueError):
    pass


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MonitorConfig(ConfigModel):
    refresh_interval_seconds: float = Field(default=2, ge=0.25, le=60)
    stale_after_seconds: float = Field(default=10, ge=1, le=3600)
    history_seconds: int = Field(default=600, ge=1, le=86400)
    http_timeout_seconds: float = Field(default=3, gt=0, le=60)
    max_concurrent_polls: int = Field(default=8, ge=1, le=64)
    max_response_bytes: int = Field(default=4194304, ge=1024, le=16777216)


class AuthConfig(ConfigModel):
    kind: Literal["none", "bearer"] = "none"
    token_env: str | None = None

    @model_validator(mode="after")
    def validate_reference(self) -> AuthConfig:
        if self.kind == "bearer" and not self.token_env:
            raise ValueError("bearer authentication requires token_env")
        if self.token_env and not self.token_env.replace("_", "").isalnum():
            raise ValueError("token_env must be an environment variable name")
        return self

    def headers(self) -> dict[str, str]:
        if self.kind == "none":
            return {}
        token = os.environ.get(self.token_env or "")
        if not token:
            raise ConfigError(f"Missing credential environment variable: {self.token_env}")
        if "\r" in token or "\n" in token:
            raise ConfigError("Credential contains invalid header characters")
        return {"Authorization": f"Bearer {token}"}


class HostConfig(ConfigModel):
    id: str
    label: str
    collector: Literal["local", "disabled"] = "local"
    hardware_scope: Literal["host", "vm", "container"] = "host"
    gpu_provider: Literal["auto", "none", "nvml", "nvidia-smi"] = "auto"


class ServiceConfig(ConfigModel):
    id: str
    label: str
    host_id: str
    engine: Literal["vllm", "llamacpp", "sglang", "ollama"]
    enabled: bool = True
    api_url: str
    metrics_url: str | None = None
    health_path: str = "/health"
    slots_path: str | None = None
    loaded_models_path: str | None = None
    deployment_profile: str | None = None
    engine_version: str | None = None
    api_auth: AuthConfig = Field(default_factory=AuthConfig)
    metrics_auth: AuthConfig = Field(default_factory=AuthConfig)
    metric_selection: dict[str, str] = Field(default_factory=dict)

    @field_validator("api_url", "metrics_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname:
            raise ValueError("Endpoint must be an absolute HTTP(S) URL")
        if url.username or url.password or url.fragment:
            raise ValueError("Credentials and fragments are not allowed in endpoint URLs")
        if any(k.lower() in {"token", "key", "api_key", "secret"} for k in parse_qs(url.query)):
            raise ValueError("Use environment references instead of URL credentials")
        return value.rstrip("/")

    @field_validator("health_path", "slots_path", "loaded_models_path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        if value is not None and (not value.startswith("/") or value.startswith("//")):
            raise ValueError("API paths must be relative to the configured origin")
        return value


class TuiConfig(ConfigModel):
    enabled: bool = True
    theme: Literal["auto", "dark", "light"] = "auto"
    ascii: bool = False
    connect_url: str | None = None


class WebConfig(ConfigModel):
    enabled: bool = True
    bind_host: Literal["127.0.0.1", "::1", "localhost"] = "127.0.0.1"
    port: int = Field(default=8787, ge=1024, le=65535)
    enable_remote: Literal[False] = False
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:8787"])
    update_transport: Literal["sse"] = "sse"
    poll_fallback_seconds: float = Field(default=2, ge=0.5, le=60)


class PrivacyConfig(ConfigModel):
    source_ip_mode: str = "hmac"
    source_hash_secret_env: str = "LLMTOP_SOURCE_HASH_SECRET"
    capture_prompt: Literal[False] = False
    capture_response: Literal[False] = False
    request_retention_seconds: int = Field(default=3600, ge=1)
    max_request_events: int = Field(default=10000, ge=1)


class UpdateConfig(ConfigModel):
    source_url: str = ""
    allow_prerelease: bool = False

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        if not value:
            return value
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname:
            raise ValueError("Update source must be an absolute HTTPS URL")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Update source must not contain credentials, query or fragment")
        return value.rstrip("/") + "/"


class RequestSourceConfig(ConfigModel):
    id: str
    kind: Literal["jsonl"]
    enabled: bool = False
    path: str
    service_ids: list[str]
    coverage: str = "partial"
    trust: str = "verified_gateway"


class Config(ConfigModel):
    schema_version: Literal[1] = 1
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    tui: TuiConfig = Field(default_factory=TuiConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    update: UpdateConfig = Field(default_factory=UpdateConfig)
    hosts: list[HostConfig]
    services: list[ServiceConfig] = Field(default_factory=list)
    request_sources: list[RequestSourceConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def inventory(self) -> Config:
        for name in ("hosts", "services", "request_sources"):
            ids = [item.id for item in getattr(self, name)]
            if len(ids) != len(set(ids)) or any(not item for item in ids):
                raise ValueError(f"{name} ids must be nonempty and unique")
        host_ids = {h.id for h in self.hosts}
        service_ids = {s.id for s in self.services}
        if host_ids & service_ids:
            raise ValueError("Host and service IDs must use distinct namespaces")
        for service in self.services:
            if service.host_id not in host_ids:
                raise ValueError(f"Unknown host_id for service {service.id}")
        for source in self.request_sources:
            if not set(source.service_ids) <= service_ids:
                raise ValueError(f"Unknown service_ids for request source {source.id}")
            if source.enabled:
                raise ValueError("Request event ingestion is scheduled for M2; disable this source")
        if sum(host.collector == "local" for host in self.hosts) > 1:
            raise ValueError("Only one host may represent this runtime's local OS")
        if self.monitor.stale_after_seconds < self.monitor.refresh_interval_seconds:
            raise ValueError("stale_after_seconds must be at least the refresh interval")
        return self


def user_config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        setting = os.environ.get("XDG_CONFIG_HOME", "")
        base = Path(setting) if setting and Path(setting).is_absolute() else Path.home() / ".config"
    return base / "llmtop" / "llmtop.toml"


def configured_path(path: str | Path | None = None) -> Path:
    """Choose a write target without falling back to the working directory."""
    selected = path if path is not None else os.environ.get("LLMTOP_CONFIG")
    return Path(selected).expanduser().absolute() if selected else user_config_path()


def resolve_config_path(path: str | Path | None = None) -> Path:
    selected = configured_path(path)
    if path is not None or os.environ.get("LLMTOP_CONFIG") or selected.exists():
        return selected
    legacy = Path.cwd() / "llmtop.toml"
    return legacy if legacy.is_file() else selected


def config_template() -> str:
    return files("llmtop").joinpath("resources", "llmtop.toml").read_text(encoding="utf-8")


def init_config(path: str | Path | None = None) -> Path:
    target = configured_path(path)
    try:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(config_template())
    except FileExistsError:
        raise ConfigError(
            "Configuration already exists; edit it or use --config for a new file"
        ) from None
    except OSError:
        raise ConfigError(
            "Unable to create the configuration; check the target directory"
        ) from None
    return target


def load_config(path: str | Path | None = None) -> Config:
    selected = resolve_config_path(path)
    try:
        with selected.open("rb") as source:
            return Config.model_validate(tomllib.load(source))
    except (OSError, ValueError) as exc:
        # ValidationError includes input values; don't expose raw configuration or secrets.
        if isinstance(exc, OSError):
            raise ConfigError(
                "Unable to read the configuration. Run llmtop init, or select an existing file "
                "with --config or LLMTOP_CONFIG"
            ) from None
        raise ConfigError(
            "Invalid configuration; check types, references, paths and supported fields"
        ) from None


def demo_config() -> Config:
    return Config(
        hosts=[HostConfig(id="demo-host", label="Demo host", hardware_scope="vm")],
        services=[
            ServiceConfig(
                id="atlas-vllm",
                label="atlas-vllm",
                host_id="demo-host",
                engine="vllm",
                api_url="http://127.0.0.1:18081",
                metric_selection={"model_name": "Llama-3.1-8B"},
            ),
            ServiceConfig(
                id="workbench-llama",
                label="workbench-llama",
                host_id="demo-host",
                engine="llamacpp",
                api_url="http://127.0.0.1:18082",
                metric_selection={"model_name": "Qwen2.5-7B"},
            ),
            ServiceConfig(
                id="edge-vllm",
                label="edge-vllm",
                host_id="demo-host",
                engine="vllm",
                api_url="http://127.0.0.1:18083",
                metric_selection={"model_name": "Mistral-7B"},
            ),
        ],
    )
