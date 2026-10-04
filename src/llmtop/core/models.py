from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field


def utc_now() -> datetime:
    return datetime.now(UTC)


class Status(StrEnum):
    OK = "ok"
    WARMING_UP = "warming_up"
    NO_DATA = "no_data"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    PERMISSION_DENIED = "permission_denied"
    ERROR = "error"
    STALE = "stale"


class Health(StrEnum):
    REACHABLE = "reachable"
    LOADING = "loading"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    AUTH_ERROR = "auth_error"
    UNKNOWN = "unknown"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Observation(Model):
    metric: str
    value: float | None = None
    unit: str
    status: Status = Status.NO_DATA
    host_id: str
    service_id: str | None = None
    device_id: str | None = None
    model_id: str | None = None
    source_kind: str
    source_metric: str | None = None
    scope: str = "engine"
    aggregation: str = "none"
    measurement_kind: str = "observed"
    observed_at: datetime = Field(default_factory=utc_now)
    last_success_at: datetime | None = None
    window_seconds: float | None = None
    source_period_seconds: float | None = None
    epoch: str | None = None
    semantics: str | None = None
    coverage: str = "unknown"
    reason: str | None = None


class Capability(Model):
    metric: str
    support: str
    source: str | None = None
    reason: str | None = None


class Service(Model):
    id: str
    label: str
    host_id: str
    engine: str
    model_name: str | None = None
    engine_version: str | None = None
    version_verified: bool = False
    health: Health = Health.UNKNOWN
    reason: str | None = None
    last_success_at: datetime | None = None
    metrics: dict[str, Observation] = Field(default_factory=dict)
    capabilities: list[Capability] = Field(default_factory=list)
    selected_labels: dict[str, str] = Field(default_factory=dict)


class Device(Model):
    id: str
    label: str
    provider: str
    driver_version: str | None = None
    metrics: dict[str, Observation] = Field(default_factory=dict)


class Host(Model):
    id: str
    label: str
    scope: str = "host"
    collector: str
    metrics: dict[str, Observation] = Field(default_factory=dict)
    devices: list[Device] = Field(default_factory=list)
    reason: str | None = None


class Snapshot(Model):
    schema_version: int = 1
    runtime_id: str
    snapshot_seq: int
    collected_at: datetime = Field(default_factory=utc_now)
    demo: bool = False
    refresh_interval_seconds: float
    stale_after_seconds: float = 10
    services: list[Service]
    hosts: list[Host]

    @computed_field
    @property
    def metrics(self) -> list[Observation]:
        result = [m for service in self.services for m in service.metrics.values()]
        for host in self.hosts:
            result.extend(host.metrics.values())
            for device in host.devices:
                result.extend(device.metrics.values())
        return result
