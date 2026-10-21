"""Official-source version checks, atomic updates, and rollback for managed installs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

from llmtop import __version__
from llmtop.installer import MARKER, install_lock, install_wheel, read_receipt

SUMS_NAME = "SHA256SUMS"
MAX_SUMS_BYTES = 1 << 20
MAX_CONSTRAINTS_BYTES = 4 << 20
MAX_WHEEL_BYTES = 256 << 20
WHEEL_PATTERN = re.compile(r"^llmtop-([0-9][A-Za-z0-9.!+_-]*)-py3-none-any\.whl$")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
SAFE_NAME_PATTERN = re.compile(r"[A-Za-z0-9._+-]+")


class UpdateError(ValueError):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    wheel_name: str
    wheel_sha256: str
    constraints_name: str | None = None
    constraints_sha256: str | None = None


@dataclass(frozen=True)
class CheckResult:
    current: str
    latest: str | None
    newer: bool


def parse_version(text: str) -> tuple[tuple[int, ...], str]:
    match = re.fullmatch(r"(\d+(?:\.\d+)*)(.*)", text)
    if not match:
        raise UpdateError("Update source lists an unrecognized version")
    return tuple(int(part) for part in match.group(1).split(".")), match.group(2)


def is_newer(candidate: str, current: str, allow_prerelease: bool = False) -> bool:
    candidate_numbers, candidate_suffix = parse_version(candidate)
    current_numbers, current_suffix = parse_version(current)
    if candidate_suffix and not allow_prerelease:
        return False
    if candidate_numbers != current_numbers:
        return candidate_numbers > current_numbers
    return bool(current_suffix) and not candidate_suffix


def parse_sums(text: str) -> dict[str, str]:
    sums = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, separator, name = line.partition("  ")
        if (
            not separator
            or not SHA256_PATTERN.fullmatch(digest)
            or not SAFE_NAME_PATTERN.fullmatch(name.strip())
        ):
            raise UpdateError("Update source manifest is malformed")
        sums[name.strip()] = digest
    return sums


def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(10, read=60), follow_redirects=True, trust_env=False)


def fetch_sums(source_url: str) -> dict[str, str]:
    try:
        with _client() as client:
            response = client.get(source_url.rstrip("/") + "/" + SUMS_NAME)
            response.raise_for_status()
    except httpx.HTTPError:
        raise UpdateError("Unable to reach the configured update source") from None
    if urlsplit(str(response.url)).scheme != "https":
        raise UpdateError("Update source redirects outside HTTPS")
    if len(response.content) > MAX_SUMS_BYTES:
        raise UpdateError("Update source manifest is too large")
    try:
        return parse_sums(response.content.decode("utf-8"))
    except UnicodeDecodeError:
        raise UpdateError("Update source manifest is malformed") from None


def latest_release(source_url: str, allow_prerelease: bool = False) -> Release | None:
    sums = fetch_sums(source_url)
    candidates = []
    for name, digest in sums.items():
        match = WHEEL_PATTERN.fullmatch(name)
        if match:
            candidates.append((parse_version(match.group(1)), match.group(1), name, digest))
    if not candidates:
        return None
    _, version, wheel_name, wheel_sha256 = max(candidates, key=lambda item: item[0])
    constraints_name = f"llmtop-{version}-dependency-constraints.txt"
    constraints_sha256 = sums.get(constraints_name)
    if constraints_name in sums and not constraints_sha256:
        raise UpdateError("Update source manifest is malformed")
    return Release(version, wheel_name, wheel_sha256, constraints_name, constraints_sha256)


def download(url: str, target: Path, expected_sha256: str, max_bytes: int) -> None:
    if urlsplit(url).scheme != "https":
        raise UpdateError("Update source redirects outside HTTPS")
    digest = hashlib.sha256()
    size = 0
    try:
        with _client() as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                if urlsplit(str(response.url)).scheme != "https":
                    raise UpdateError("Update source redirects outside HTTPS")
                with target.open("wb") as output:
                    for chunk in response.iter_bytes(1 << 16):
                        size += len(chunk)
                        if size > max_bytes:
                            raise UpdateError("Update download exceeds the size limit")
                        digest.update(chunk)
                        output.write(chunk)
    except httpx.HTTPError:
        raise UpdateError("Unable to download from the configured update source") from None
    if digest.hexdigest() != expected_sha256:
        target.unlink(missing_ok=True)
        raise UpdateError("Update download checksum does not match the source manifest")


def detect_install_root(start: str | Path | None = None) -> Path | None:
    path = Path(start or sys.executable).resolve()
    for parent in path.parents:
        if (parent / MARKER).is_file() and (parent / "environments").is_dir():
            return parent
    return None


def check_for_update(source_url: str, allow_prerelease: bool = False) -> CheckResult:
    release = latest_release(source_url, allow_prerelease)
    newer = release is not None and is_newer(release.version, __version__, allow_prerelease)
    return CheckResult(__version__, release.version if release else None, newer)


def _install_from_staging(
    root: Path, wheel: Path, constraints: Path | None, source: str | None
) -> dict:
    receipt = read_receipt(root)
    return install_wheel(
        wheel=wheel,
        root=root,
        bin_dir=Path(receipt["launcher"]).parent,
        python=sys.executable,
        gpu="gpu" in receipt.get("extras", []),
        constraints=constraints,
        ensure_path=False,
        source=source,
    )


def update_from_source(root: Path, source_url: str, allow_prerelease: bool = False) -> dict | None:
    receipt = read_receipt(root)
    release = latest_release(source_url, allow_prerelease)
    if release is None or not is_newer(release.version, receipt["version"], allow_prerelease):
        return None
    staging = root / ".tmp" / f"update-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, mode=0o700)
    try:
        wheel = staging / release.wheel_name
        download(
            source_url.rstrip("/") + "/" + quote(release.wheel_name),
            wheel,
            release.wheel_sha256,
            MAX_WHEEL_BYTES,
        )
        constraints = None
        if release.constraints_name and release.constraints_sha256:
            constraints = staging / release.constraints_name
            download(
                source_url.rstrip("/") + "/" + quote(release.constraints_name),
                constraints,
                release.constraints_sha256,
                MAX_CONSTRAINTS_BYTES,
            )
        return _install_from_staging(root, wheel, constraints, source_url)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def update_from_wheel(root: Path, wheel: Path) -> dict:
    wheel = wheel.expanduser().resolve(strict=True)
    staging = root / ".tmp" / f"update-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, mode=0o700)
    try:
        staged = staging / wheel.name
        shutil.copyfile(wheel, staged)
        return _install_from_staging(root, staged, None, None)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def environment_version(environment: Path) -> str:
    for metadata in environment.glob("lib/python*/site-packages/llmtop-*.dist-info"):
        version = metadata.name[len("llmtop-") : -len(".dist-info")]
        if re.fullmatch(r"[0-9][A-Za-z0-9.!+_-]*", version):
            return version
    raise UpdateError("Unable to determine the previous environment version")


def rollback(root: Path) -> dict:
    with install_lock(root):
        receipt = read_receipt(root)
        previous = receipt.get("previous_environment")
        if not previous:
            raise UpdateError("No previous environment to roll back to")
        target = Path(previous).expanduser().resolve()
        try:
            target.relative_to((root / "environments").resolve())
        except ValueError:
            raise UpdateError("Previous environment is outside this install directory") from None
        if not (target / "bin" / "llmtop").is_file():
            raise UpdateError("Previous environment is missing or incomplete")
        current = root / "current"
        if current.exists() and not current.is_symlink():
            raise UpdateError("Current environment is not a managed symlink")
        current_target = current.readlink() if current.is_symlink() else None
        version = receipt.get("previous_version") or environment_version(target)
        pending = root / f".current-{uuid.uuid4().hex}"
        pending.symlink_to(target)
        os.replace(pending, current)
        rolled_back = {
            **receipt,
            "version": version,
            "environment": str(target),
            "previous_environment": str(current_target) if current_target else None,
            "previous_version": receipt.get("version"),
            "wheel_sha256": None,
            "source": None,
        }
        receipt_path = root / ".receipt-new.json"
        receipt_path.write_text(json.dumps(rolled_back, indent=2) + "\n", encoding="utf-8")
        os.replace(receipt_path, root / MARKER)
        return rolled_back
