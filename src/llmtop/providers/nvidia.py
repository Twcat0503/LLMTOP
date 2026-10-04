from __future__ import annotations

import csv
import math
import shutil
import subprocess

from llmtop.config import HostConfig
from llmtop.core.models import Device, Observation, Status, utc_now

GPU_FIELDS = {
    "gpu_utilization_ratio": ("ratio", 100),
    "gpu_memory_used_bytes": ("bytes", 1 / 1048576),
    "gpu_memory_total_bytes": ("bytes", 1 / 1048576),
    "gpu_temperature_celsius": ("°C", 1),
    "gpu_power_watts": ("W", 1),
}


def gpu_observations(
    config: HostConfig, device_id: str, values: dict[str, float | None], provider: str
) -> dict[str, Observation]:
    now = utc_now()
    result = {}
    for metric, (unit, _) in GPU_FIELDS.items():
        value = values.get(metric)
        result[metric] = Observation(
            metric=metric,
            value=value,
            unit=unit,
            status=Status.OK if value is not None else Status.UNSUPPORTED,
            host_id=config.id,
            device_id=device_id,
            scope="device",
            source_kind="device_provider",
            source_metric=provider + "." + metric,
            observed_at=now,
            last_success_at=now if value is not None else None,
            reason=None if value is not None else "Device does not expose this field",
        )
    return result


def parse_smi(text: str, config: HostConfig) -> list[Device]:
    devices = []
    for row in csv.reader(text.splitlines(), skipinitialspace=True):
        if len(row) != 8:
            raise ValueError("Unexpected nvidia-smi column count")
        uuid, label, driver, *raw = [part.strip() for part in row]
        values = {}
        for (metric, (_, divisor)), value in zip(GPU_FIELDS.items(), raw, strict=True):
            try:
                parsed = float(value) / divisor
                values[metric] = parsed if math.isfinite(parsed) and parsed >= 0 else None
            except ValueError:
                values[metric] = None
        if not uuid:
            raise ValueError("GPU identity is missing")
        devices.append(
            Device(
                id=uuid,
                label=label,
                provider="nvidia-smi",
                driver_version=driver,
                metrics=gpu_observations(config, uuid, values, "nvidia-smi"),
            )
        )
    return devices


class NvidiaProvider:
    def __init__(self, config: HostConfig):
        self.config = config
        self.nvml = None
        self.nvml_ready = False
        self.initialized = False

    def initialize(self) -> None:
        config = self.config
        self.initialized = True
        if config.gpu_provider in {"auto", "nvml"}:
            try:
                import pynvml

                self.nvml = pynvml
                pynvml.nvmlInit()
                self.nvml_ready = True
            except Exception:
                # NVML may raise vendor-specific errors; all are isolated to this provider.
                self.nvml_ready = False

    def collect(self) -> tuple[list[Device], str | None]:
        if self.config.gpu_provider == "none" or self.config.collector != "local":
            return [], None
        if not self.initialized:
            self.initialize()
        if self.nvml_ready:
            try:
                return self.collect_nvml(), None
            except Exception:
                if self.config.gpu_provider == "nvml":
                    return [], "NVML device metrics unavailable"
        if self.config.gpu_provider == "nvml":
            return [], "NVML is not installed or the driver is unavailable"
        command = shutil.which("nvidia-smi")
        if not command:
            return [], "GPU provider unavailable on this host"
        try:
            result = subprocess.run(
                [
                    command,
                    "--query-gpu=uuid,name,driver_version,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if result.returncode:
                return [], "nvidia-smi could not read device metrics"
            return parse_smi(result.stdout, self.config), None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return [], "GPU collection failed or timed out"

    def collect_nvml(self) -> list[Device]:
        nvml = self.nvml
        devices = []

        def query(callback, *args):
            try:
                return callback(*args)
            except Exception:
                return None

        for index in range(nvml.nvmlDeviceGetCount()):
            handle = nvml.nvmlDeviceGetHandleByIndex(index)
            uuid = nvml.nvmlDeviceGetUUID(handle)
            name = nvml.nvmlDeviceGetName(handle)
            uuid = uuid.decode() if isinstance(uuid, bytes) else uuid
            name = name.decode() if isinstance(name, bytes) else name
            usage = query(nvml.nvmlDeviceGetUtilizationRates, handle)
            memory = query(nvml.nvmlDeviceGetMemoryInfo, handle)
            power = query(nvml.nvmlDeviceGetPowerUsage, handle)
            values = {
                "gpu_utilization_ratio": usage.gpu / 100 if usage else None,
                "gpu_memory_used_bytes": memory.used if memory else None,
                "gpu_memory_total_bytes": memory.total if memory else None,
                "gpu_temperature_celsius": query(
                    nvml.nvmlDeviceGetTemperature, handle, nvml.NVML_TEMPERATURE_GPU
                ),
                "gpu_power_watts": power / 1000 if power is not None else None,
            }
            driver = query(nvml.nvmlSystemGetDriverVersion)
            driver = driver.decode() if isinstance(driver, bytes) else driver
            devices.append(
                Device(
                    id=uuid,
                    label=name,
                    provider="nvml",
                    driver_version=driver,
                    metrics=gpu_observations(self.config, uuid, values, "nvml"),
                )
            )
        return devices

    def close(self) -> None:
        if self.nvml_ready:
            try:
                self.nvml.nvmlShutdown()
            except Exception:
                pass
            self.nvml_ready = False
