"""Install a built LLMTOP wheel for one Linux/macOS user, without root."""

from __future__ import annotations

import argparse
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
from email.parser import BytesParser
from pathlib import Path

MARKER = ".llmtop-install.json"
PATH_START = "# >>> LLMTOP PATH >>>"
PATH_END = "# <<< LLMTOP PATH <<<"


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


def install(args: argparse.Namespace) -> dict:
    if sys.platform == "win32":
        raise InstallError("This installer targets Linux and macOS")
    wheel = args.wheel.expanduser().resolve(strict=True)
    version = wheel_version(wheel)
    root = args.install_dir.expanduser().resolve()
    bin_dir = args.bin_dir.expanduser().resolve()
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
    if marker.is_file():
        previous = json.loads(marker.read_text(encoding="utf-8"))
        if previous.get("kind") != "llmtop-user-install" or previous.get("schema_version") != 1:
            raise InstallError("Unrecognized install directory marker")
    changes = (
        profile_changes(bin_dir, Path.home(), Path(os.environ.get("SHELL", "/bin/sh")).name)
        if args.ensure_path
        else {}
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = root / ".install.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise InstallError("Another installation is in progress; check .install.lock") from None
    os.close(descriptor)
    release = root / "environments" / f"{version}-{uuid.uuid4().hex}"
    current = root / "current"
    if current.exists() and not current.is_symlink():
        lock.unlink()
        raise InstallError("Current environment is not a managed symlink")
    previous_target = current.readlink() if current.is_symlink() else None
    if previous_target is not None:
        try:
            (current.parent / previous_target).resolve().relative_to(root / "environments")
        except ValueError:
            lock.unlink()
            raise InstallError("Current environment is outside this install directory") from None
    pending = root / f".current-{uuid.uuid4().hex}"
    activated = False
    created_launcher = False
    try:
        if not marker.exists():
            marker.write_text(
                json.dumps({"kind": "llmtop-user-install", "schema_version": 1}), encoding="utf-8"
            )
        environment = os.environ.copy()
        environment["TMPDIR"] = str(root / ".tmp")
        environment["PIP_CACHE_DIR"] = str(root / ".cache" / "pip")
        Path(environment["TMPDIR"]).mkdir(mode=0o700, exist_ok=True)
        checked([args.python, "-m", "venv", str(release)], root, environment)
        python = release / "bin" / "python"
        command = [
            str(python),
            "-m",
            "pip",
            "--isolated",
            "install",
            "--disable-pip-version-check",
            "--cache-dir",
            environment["PIP_CACHE_DIR"],
        ]
        if args.wheelhouse:
            command.extend(["--no-index", "--find-links", str(args.wheelhouse.resolve())])
        if args.constraints:
            command.extend(["--constraint", str(args.constraints.resolve(strict=True))])
        command.append(str(wheel) + ("[gpu]" if args.gpu else ""))
        checked(command, root, environment)
        checked([str(python), "-m", "pip", "check"], root, environment)
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
            "kind": "llmtop-user-install",
            "schema_version": 1,
            "version": version,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "environment": str(release),
            "previous_environment": str(previous_target) if previous_target else None,
            "launcher": str(launcher),
            "path_profiles": [str(path) for path in changes],
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
        lock.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--install-dir", type=Path, default=Path.home() / ".local/share/llmtop")
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--gpu", action="store_true")
    parser.add_argument("--constraints", type=Path, help="Exported locked dependency constraints")
    parser.add_argument(
        "--wheelhouse", type=Path, help="Install offline using this dependency directory"
    )
    parser.add_argument(
        "--ensure-path", action="store_true", help="Append an idempotent shell PATH block"
    )
    args = parser.parse_args(argv)
    try:
        receipt = install(args)
    except InstallError as exc:
        print(f"LLMTOP installation failed: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, subprocess.TimeoutExpired):
        # Keep detailed tool output in the private installation log.
        print(
            "LLMTOP installation failed. Check paths, wheel and installation.log.", file=sys.stderr
        )
        return 2
    print(f"Installed LLMTOP {receipt['version']} at {receipt['launcher']}")
    print(
        "Open a new login shell, or run: "
        + f'export PATH={shlex.quote(str(args.bin_dir.expanduser().resolve()))}:"$PATH"'
    )
    print("Then run: llmtop init; llmtop doctor; llmtop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
