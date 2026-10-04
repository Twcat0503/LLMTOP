"""Audit public source candidates and optional LLMTOP release archives."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

PRIVATE_FILES = {
    "llmtop",
    "llmtop.toml",
    "AGENTS.md",
    ".release-private-patterns",
    "source-manifest.json",
    ".llmtop-task",
    "docs/TEST-ENVIRONMENT.md",
    "docs/M1-VALIDATION.md",
    "docs/PROTOTYPE-AUDIT.md",
}
PRIVATE_PARTS = {
    ".git",
    ".remote",
    ".tools",
    ".bootstrap",
    ".cache",
    ".tmp",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "artifacts",
    "logs",
    "data",
    "test-results",
    "playwright-report",
}
SECRET_RULES = {
    "private key": rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
    "credential-shaped token": rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{30,})\b",
    "workstation path": rb"(?:/home/[A-Za-z0-9_.-]+/|[A-Z]:\\Users\\[A-Za-z0-9_.-]+\\)",
}


def blocked_path(name: str) -> bool:
    path = PurePosixPath(name)
    filename = path.name
    return (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or any(character in name for character in ("\n", "\r", "\0"))
        or name in PRIVATE_FILES
        or any(part in PRIVATE_PARTS for part in path.parts)
        or name.startswith("docs/design/")
        or filename.endswith("-LOCAL.md")
        or filename.endswith(
            (".local.toml", ".pem", ".key", ".pub", ".p12", ".pfx", ".log", ".pyc")
        )
        or (filename.startswith(".env") and not filename.endswith(".example"))
    )


def scan(files: dict[str, bytes], patterns: list[bytes]) -> list[str]:
    errors = []
    for name, content in files.items():
        if blocked_path(name):
            errors.append(f"{name}: excluded private path")
        for label, expression in SECRET_RULES.items():
            if re.search(expression, content):
                errors.append(f"{name}: {label}")
        if any(pattern.lower() in content.lower() for pattern in patterns):
            errors.append(f"{name}: configured private pattern")
    return errors


def link_errors(files: dict[str, bytes]) -> list[str]:
    errors = []
    for name, content in files.items():
        if not name.endswith(".md"):
            continue
        for target in re.findall(r"!?\[[^\]]*\]\(([^\s)]+)\)", content.decode("utf-8-sig")):
            target = unquote(target.strip("<>"))
            if urlsplit(target).scheme or target.startswith("#"):
                continue
            target = target.split("#", 1)[0]
            parts = list(PurePosixPath(name).parent.parts)
            for part in PurePosixPath(target).parts:
                if part == "..":
                    if parts:
                        parts.pop()
                elif part != ".":
                    parts.append(part)
            if "/".join(parts) not in files:
                errors.append(f"{name}: link points outside public files")
    return errors


def runtime_version(content: bytes) -> str | None:
    for statement in ast.parse(content.decode("utf-8-sig")).body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in statement.targets
        ):
            return ast.literal_eval(statement.value)
    return None


def source_files(root: Path, file_list: Path | None) -> dict[str, bytes]:
    if file_list:
        manifest = json.loads(file_list.read_text(encoding="utf-8-sig"))
        entries = manifest["files"]
        names = [entry["path"] for entry in entries]
    else:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            check=True,
        )
        names = list(dict.fromkeys(result.stdout.decode("utf-8").rstrip("\0").split("\0")))
        entries = []
    files = {}
    for name in names:
        if not name:
            continue
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Source list contains a symlink or a path outside the project")
        files[name] = path.read_bytes()
    for entry in entries:
        if hashlib.sha256(files[entry["path"]]).hexdigest() != entry["sha256"]:
            raise ValueError("Source manifest hash does not match the files")
    return files


def archive_files(path: Path, wheel: bool) -> dict[str, bytes]:
    if wheel:
        with zipfile.ZipFile(path) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if any((item.external_attr >> 16) & 0o170000 == 0o120000 for item in members):
                raise ValueError("Wheel contains symlinks")
            return {item.filename: archive.read(item) for item in members}
    with tarfile.open(path, "r:gz") as archive:
        members = [item for item in archive.getmembers() if not item.isdir()]
        if any(not item.isfile() or "/" not in item.name for item in members):
            raise ValueError("Source archive contains unsupported entries")
        roots = {item.name.split("/", 1)[0] for item in members}
        if len(roots) != 1:
            raise ValueError("Source archive must have one project root")
        return {item.name.split("/", 1)[1]: archive.extractfile(item).read() for item in members}


def audit(
    root: Path, file_list: Path | None, patterns: list[bytes], packages: list[tuple[Path, bool]]
) -> dict:
    files = source_files(root, file_list)
    errors = scan(files, patterns) + link_errors(files)
    project = tomllib.loads(files["pyproject.toml"].decode("utf-8-sig"))["project"]
    version = project["version"]
    if runtime_version(files["src/llmtop/__init__.py"]) != version or any(
        json.loads(files[name])["version"] != version
        for name in ("frontend/package.json", "frontend/package-lock.json")
    ):
        errors.append("source: Python and frontend versions disagree")
    results = []
    for package, wheel in packages:
        content = archive_files(package, wheel)
        errors.extend(f"{package.name}/{error}" for error in scan(content, patterns))
        metadata_name = (
            next((name for name in content if name.endswith(".dist-info/METADATA")), None)
            if wheel
            else "PKG-INFO"
        )
        metadata = BytesParser().parsebytes(content.get(metadata_name, b""))
        if (
            metadata.get("Name") != "llmtop"
            or metadata.get("Version") != version
            or metadata.get("License-Expression") != "MIT"
        ):
            errors.append(f"{package.name}: package metadata mismatch")
        if not any(name.endswith("/LICENSE") or name == "LICENSE" for name in content):
            errors.append(f"{package.name}: missing MIT license")
        web_prefix = "llmtop/web_static/" if wheel else "src/llmtop/web_static/"
        if json.loads(content.get(web_prefix + "build-info.json", b"{}")).get("version") != version:
            errors.append(f"{package.name}: Web version mismatch")
        if wheel:
            if (
                "llmtop/resources/llmtop.toml" not in content
                or "llmtop/web_static/index.html" not in content
                or not any(
                    name.startswith("llmtop/web_static/assets/") and name.endswith(".js")
                    for name in content
                )
            ):
                errors.append(f"{package.name}: missing initialization template or Web assets")
            if runtime_version(content.get("llmtop/__init__.py", b"")) != version:
                errors.append(f"{package.name}: runtime version mismatch")
        results.append(
            {
                "file": package.name,
                "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
                "files": len(content),
            }
        )
    fingerprint = hashlib.sha256(
        json.dumps(
            {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return {
        "version": version,
        "source_files": len(files),
        "source_sha256": fingerprint,
        "packages": results,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--file-list", type=Path, help="Hashed source manifest when Git is unavailable"
    )
    parser.add_argument("--private-patterns", type=Path)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--sdist", type=Path)
    args = parser.parse_args(argv)
    pattern_file = args.private_patterns or args.root / ".release-private-patterns"
    patterns = (
        [
            line.strip().encode()
            for line in pattern_file.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
        if pattern_file.exists()
        else []
    )
    try:
        result = audit(
            args.root,
            args.file_list,
            patterns,
            [(path, wheel) for path, wheel in ((args.wheel, True), (args.sdist, False)) if path],
        )
    except (
        OSError,
        ValueError,
        KeyError,
        SyntaxError,
        tarfile.TarError,
        zipfile.BadZipFile,
        subprocess.CalledProcessError,
    ):
        print(
            json.dumps({"errors": ["Unable to audit source or archives; check files and manifest"]})
        )
        return 2
    print(json.dumps(result, indent=2))
    return 2 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
