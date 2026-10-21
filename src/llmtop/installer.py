"""Shared transactional install logic for managed LLMTOP user installs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import uuid
import zipfile
from contextlib import contextmanager
from email.parser import BytesParser
from pathlib import Path

MARKER = ".llmtop-install.json"
PATH_START = "# >>> LLMTOP PATH >>>"
PATH_END = "# <<< LLMTOP PATH <<<"
RECEIPT_KIND = "llmtop-user-install"
RECEIPT_SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = {1, 2}


class InstallError(ValueError):
    pass


def wheel_version(wheel: Path) -> str:
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            metadata_files = [name for name in names if name.endswith(".dist-info/METADATA")]
            if len(metadata_files) != 1:
                raise InstallError("Expected one LLMTOP wheel metadata file")
            metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
            version = str(metadata.get("Version", ""))
            if metadata.get("Name", "").lower() != "llmtop" or not re.fullmatch(
                r"[0-9][A-Za-z0-9.!+_-]*", version
            ):
                raise InstallError("Wheel must contain the LLMTOP package and a valid version")
            if "llmtop/web_static/index.html" not in names or not any(
                name.startswith("llmtop/web_static/assets/") and name.endswith(".js")
                for name in names
            ):
                raise InstallError("Wheel has no built Web assets; build frontend before packaging")
            if (
                json.loads(archive.read("llmtop/web_static/build-info.json")).get("version")
                != version
            ):
                raise InstallError("Wheel Web assets do not match the Python version")
            return version
    except (OSError, zipfile.BadZipFile, KeyError):
        raise InstallError("Unable to read the wheel") from None


def path_block(bin_dir: Path) -> str:
    if any(character in str(bin_dir) for character in (":", "\n", "\r")):
        raise InstallError("Bin directory cannot contain PATH separators or newlines")
    return (
        f"{PATH_START}\n"
        f"_llmtop_bin={shlex.quote(str(bin_dir))}\n"
        'case ":$PATH:" in\n'
        '  *":$_llmtop_bin:"*) ;;\n'
        '  *) export PATH="$_llmtop_bin:$PATH" ;;\n'
        "esac\n"
        "unset _llmtop_bin\n"
        f"{PATH_END}\n"
    )


def profile_changes(bin_dir: Path, home: Path, shell: str) -> dict[Path, str]:
    block = path_block(bin_dir)
    if shell == "bash":
        login = next(
            (home / name for name in (".bash_profile", ".bash_login") if (home / name).exists()),
            home / ".profile",
        )
        profiles = [login, home / ".bashrc"]
    elif shell == "zsh":
        base = Path(os.environ.get("ZDOTDIR") or home).expanduser().absolute()
        profiles = [base / ".zprofile", base / ".zshrc"]
    elif shell in {"sh", "dash", "ksh"}:
        profiles = [home / ".profile"]
    else:
        raise InstallError(
            "Automatic PATH setup supports bash, zsh and POSIX sh; omit --ensure-path"
        )
    changes = {}
    for profile in profiles:
        existing = profile.read_text(encoding="utf-8") if profile.exists() else ""
        if PATH_START in existing or PATH_END in existing:
            if (
                existing.count(PATH_START) != 1
                or existing.count(PATH_END) != 1
                or block not in existing
            ):
                raise InstallError(
                    "A different LLMTOP PATH block exists; review your shell profiles"
                )
        else:
            changes[profile] = ("\n" if existing and not existing.endswith("\n") else "") + block
    return changes


def checked(command: list[str], root: Path, environment: dict[str, str]) -> str:
    result = subprocess.run(
        command, cwd=root, env=environment, capture_output=True, text=True, timeout=600
    )
    with (root / "installation.log").open("a", encoding="utf-8") as log:
        log.write(result.stdout + result.stderr)
    if result.returncode:
        raise InstallError(
            "Installation check failed; see installation.log in the install directory"
        )
    return result.stdout.strip()


@contextmanager
def install_lock(root: Path):
    lock = root / ".install.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise InstallError("Another installation is in progress; check .install.lock") from None
    os.close(descriptor)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def read_receipt(root: Path) -> dict:
    try:
        receipt = json.loads((root / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise InstallError("Unable to read the install receipt") from None
    if (
        not isinstance(receipt, dict)
        or receipt.get("kind") != RECEIPT_KIND
        or receipt.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS
    ):
        raise InstallError("Unrecognized install directory marker")
    if not all(receipt.get(field) for field in ("version", "environment", "launcher")):
        raise InstallError("Install receipt is incomplete; reinstall with the user installer")
    return receipt


def install_wheel(
    *,
    wheel: Path,
    root: Path,
    bin_dir: Path,
    python: str,
    gpu: bool = False,
    constraints: Path | None = None,
    wheelhouse: Path | None = None,
    ensure_path: bool = False,
    source: str | None = None,
) -> dict:
    if sys.platform == "win32":
        raise InstallError("This installer targets Linux and macOS")
    wheel = wheel.expanduser().resolve(strict=True)
    version = wheel_version(wheel)
    root = root.expanduser().resolve()
    bin_dir = bin_dir.expanduser().resolve()
    path_block(bin_dir)
    launcher = bin_dir / "llmtop"
    entry_point = root / "current" / "bin" / "llmtop"
    if launcher.exists() or launcher.is_symlink():
        if not launcher.is_symlink() or launcher.readlink() != entry_point:
            raise InstallError(
                "Bin directory already contains an unrelated llmtop; choose --bin-dir"
            )
    marker = root / MARKER
    if root.exists() and any(root.iterdir()) and not marker.is_file():
        raise InstallError("Install directory contains unrelated files; choose an empty directory")
    previous_version = None
    if marker.is_file():
        try:
            previous = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise InstallError("Unrecognized install directory marker") from None
        if (
            not isinstance(previous, dict)
            or previous.get("kind") != RECEIPT_KIND
            or previous.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS
        ):
            raise InstallError("Unrecognized install directory marker")
        previous_version = previous.get("version")
    changes = (
        profile_changes(bin_dir, Path.home(), Path(os.environ.get("SHELL", "/bin/sh")).name)
        if ensure_path
        else {}
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with install_lock(root):
        release = root / "environments" / f"{version}-{uuid.uuid4().hex}"
        current = root / "current"
        if current.exists() and not current.is_symlink():
            raise InstallError("Current environment is not a managed symlink")
        previous_target = current.readlink() if current.is_symlink() else None
        if previous_target is not None:
            try:
                (current.parent / previous_target).resolve().relative_to(root / "environments")
            except ValueError:
                raise InstallError(
                    "Current environment is outside this install directory"
                ) from None
        pending = root / f".current-{uuid.uuid4().hex}"
        activated = False
        created_launcher = False
        try:
            if not marker.exists():
                marker.write_text(
                    json.dumps({"kind": RECEIPT_KIND, "schema_version": RECEIPT_SCHEMA_VERSION}),
                    encoding="utf-8",
                )
            environment = os.environ.copy()
            environment["TMPDIR"] = str(root / ".tmp")
            environment["PIP_CACHE_DIR"] = str(root / ".cache" / "pip")
            Path(environment["TMPDIR"]).mkdir(mode=0o700, exist_ok=True)
            checked([python, "-m", "venv", str(release)], root, environment)
            python_path = release / "bin" / "python"
            command = [
                str(python_path),
                "-m",
                "pip",
                "--isolated",
                "install",
                "--disable-pip-version-check",
                "--cache-dir",
                environment["PIP_CACHE_DIR"],
            ]
            if wheelhouse:
                command.extend(["--no-index", "--find-links", str(wheelhouse.resolve())])
            if constraints:
                command.extend(["--constraint", str(constraints.resolve(strict=True))])
            command.append(str(wheel) + ("[gpu]" if gpu else ""))
            checked(command, root, environment)
            checked([str(python_path), "-m", "pip", "check"], root, environment)
            executable = release / "bin" / "llmtop"
            if checked([str(executable), "--version"], root, environment) != version:
                raise InstallError("Installed version does not match the wheel")
            json.loads(checked([str(executable), "schema"], root, environment))
            for profile, addition in changes.items():
                profile.parent.mkdir(parents=True, exist_ok=True)
                with profile.open("a", encoding="utf-8") as output:
                    output.write(addition)
            bin_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            pending.symlink_to(release)
            os.replace(pending, current)
            activated = True
            if not launcher.is_symlink():
                launcher.symlink_to(entry_point)
                created_launcher = True
            receipt = {
                "kind": RECEIPT_KIND,
                "schema_version": RECEIPT_SCHEMA_VERSION,
                "version": version,
                "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "environment": str(release),
                "previous_environment": str(previous_target) if previous_target else None,
                "previous_version": previous_version,
                "launcher": str(launcher),
                "path_profiles": [str(path) for path in changes],
                "extras": ["gpu"] if gpu else [],
                "constraints": constraints is not None,
                "source": source,
            }
            receipt_path = root / ".receipt-new.json"
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            os.replace(receipt_path, marker)
            return receipt
        except BaseException:
            if activated:
                if previous_target is None:
                    current.unlink()
                else:
                    pending.symlink_to(previous_target)
                    os.replace(pending, current)
            if created_launcher:
                launcher.unlink()
            if release.exists():
                release.resolve().relative_to(root / "environments")
                shutil.rmtree(release)
            raise
        finally:
            if pending.is_symlink():
                pending.unlink()
