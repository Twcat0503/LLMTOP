import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import httpx
import pytest

from llmtop import installer, update
from llmtop.config import UpdateConfig

SOURCE = "https://example.invalid/llmtop/releases/latest/download/"


@pytest.fixture
def wheel_020(tmp_path):
    result = tmp_path / "llmtop-0.2.0-py3-none-any.whl"
    with zipfile.ZipFile(result, "w") as archive:
        archive.writestr("llmtop-0.2.0.dist-info/METADATA", "Name: llmtop\nVersion: 0.2.0\n")
        archive.writestr("llmtop/web_static/index.html", "<!doctype html>")
        archive.writestr("llmtop/web_static/build-info.json", '{"version":"0.2.0"}')
        archive.writestr("llmtop/web_static/assets/app.js", "console.log('synthetic fixture')")
    return result


@pytest.fixture
def managed_install(tmp_path):
    root = tmp_path / "install"
    old = root / "environments" / "0.1.0-old"
    (old / "bin").mkdir(parents=True)
    (old / "bin" / "llmtop").write_text("#!/bin/sh\n")
    (root / "current").symlink_to(old)
    launcher = tmp_path / "bin" / "llmtop"
    launcher.parent.mkdir()
    launcher.symlink_to(root / "current" / "bin" / "llmtop")
    (root / installer.MARKER).write_text(
        json.dumps(
            {
                "kind": "llmtop-user-install",
                "schema_version": 2,
                "version": "0.1.0",
                "wheel_sha256": "0" * 64,
                "environment": str(old),
                "previous_environment": None,
                "previous_version": None,
                "launcher": str(launcher),
                "path_profiles": [],
                "extras": [],
                "constraints": False,
                "source": None,
            }
        ),
        encoding="utf-8",
    )
    return root


def fake_checked(version):
    def checked(command, root, environment):
        if "venv" in command:
            Path(command[-1]).joinpath("bin").mkdir(parents=True)
        if "--version" in command:
            return version
        if "schema" in command:
            return "{}"
        return ""

    return checked


def test_is_newer_rules():
    assert update.is_newer("0.2.0", "0.1.0")
    assert update.is_newer("0.10.0", "0.9.0")
    assert not update.is_newer("0.1.0", "0.1.0")
    assert not update.is_newer("1.0", "1.0.1")
    assert not update.is_newer("0.2.0rc1", "0.1.0")
    assert update.is_newer("0.2.0rc1", "0.1.0", allow_prerelease=True)
    assert update.is_newer("0.2.0", "0.2.0rc1")
    assert not update.is_newer("0.2.0rc1", "0.2.0")


def test_parse_sums_rejects_malformed_lines():
    digest = "a" * 64
    assert update.parse_sums(f"{digest}  llmtop-0.2.0-py3-none-any.whl") == {
        "llmtop-0.2.0-py3-none-any.whl": digest
    }
    with pytest.raises(update.UpdateError, match="malformed"):
        update.parse_sums("deadbeef  llmtop-0.2.0-py3-none-any.whl")
    with pytest.raises(update.UpdateError, match="malformed"):
        update.parse_sums(f"{digest}  sub/dir/llmtop-0.2.0-py3-none-any.whl")


def test_update_config_requires_https_and_normalizes():
    with pytest.raises(ValueError, match="HTTPS"):
        UpdateConfig(source_url="http://example.invalid/releases/")
    with pytest.raises(ValueError, match="credentials"):
        UpdateConfig(source_url="https://user:pw@example.invalid/releases/")
    assert UpdateConfig(source_url="https://example.invalid/a").source_url == (
        "https://example.invalid/a/"
    )


def test_check_for_update_reports_latest(monkeypatch):
    monkeypatch.setattr(
        update,
        "latest_release",
        lambda url, allow_prerelease=False: update.Release(
            "0.2.0", "llmtop-0.2.0-py3-none-any.whl", "0" * 64
        ),
    )
    result = update.check_for_update(SOURCE)
    assert result.latest == "0.2.0"
    assert result.newer
    monkeypatch.setattr(
        update,
        "latest_release",
        lambda url, allow_prerelease=False: update.Release(
            "0.0.1", "llmtop-0.0.1-py3-none-any.whl", "0" * 64
        ),
    )
    assert not update.check_for_update(SOURCE).newer


@pytest.mark.skipif(installer.sys.platform == "win32", reason="POSIX installer")
def test_download_verifies_checksum_and_size(tmp_path, monkeypatch):
    content = b"synthetic wheel bytes"
    digest = hashlib.sha256(content).hexdigest()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    monkeypatch.setattr(
        update,
        "_client",
        lambda: httpx.Client(transport=transport, follow_redirects=True, trust_env=False),
    )
    target = tmp_path / "llmtop-0.2.0-py3-none-any.whl"
    update.download("https://example.invalid/w.whl", target, digest, 1024)
    assert target.read_bytes() == content
    with pytest.raises(update.UpdateError, match="checksum"):
        update.download("https://example.invalid/w.whl", target, "0" * 64, 1024)
    assert not target.exists()
    with pytest.raises(update.UpdateError, match="size limit"):
        update.download("https://example.invalid/w.whl", target, digest, 4)


@pytest.mark.skipif(installer.sys.platform == "win32", reason="POSIX installer")
def test_update_download_failure_preserves_current(managed_install, monkeypatch):
    old = (managed_install / "current").resolve()
    monkeypatch.setattr(
        update,
        "latest_release",
        lambda url, allow_prerelease=False: update.Release(
            "0.2.0", "llmtop-0.2.0-py3-none-any.whl", "0" * 64
        ),
    )

    def failing_download(url, target, expected, cap):
        raise update.UpdateError("Unable to download from the configured update source")

    monkeypatch.setattr(update, "download", failing_download)
    with pytest.raises(update.UpdateError, match="Unable to download"):
        update.update_from_source(managed_install, SOURCE)
    assert (managed_install / "current").resolve() == old
    assert list((managed_install / "environments").iterdir()) == [old]
    assert not (managed_install / ".install.lock").exists()
    assert not any((managed_install / ".tmp").iterdir())


@pytest.mark.skipif(installer.sys.platform == "win32", reason="POSIX installer")
def test_update_swaps_and_keeps_previous(managed_install, wheel_020, monkeypatch):
    old = (managed_install / "current").resolve()
    digest = hashlib.sha256(wheel_020.read_bytes()).hexdigest()
    monkeypatch.setattr(
        update,
        "latest_release",
        lambda url, allow_prerelease=False: update.Release("0.2.0", wheel_020.name, digest),
    )
    monkeypatch.setattr(
        update, "download", lambda url, target, expected, cap: shutil.copyfile(wheel_020, target)
    )
    monkeypatch.setattr(installer, "checked", fake_checked("0.2.0"))
    receipt = update.update_from_source(managed_install, SOURCE)
    assert receipt["version"] == "0.2.0"
    assert Path(receipt["previous_environment"]).resolve() == old
    assert receipt["previous_version"] == "0.1.0"
    assert receipt["source"] == SOURCE
    assert (managed_install / "current").resolve() != old
    assert (
        (managed_install / "current")
        .resolve()
        .is_relative_to((managed_install / "environments").resolve())
    )
    assert json.loads((managed_install / installer.MARKER).read_text())["version"] == "0.2.0"
    assert not list((managed_install / ".tmp").iterdir())


@pytest.mark.skipif(installer.sys.platform == "win32", reason="POSIX installer")
def test_update_up_to_date_changes_nothing(managed_install, monkeypatch):
    monkeypatch.setattr(
        update,
        "latest_release",
        lambda url, allow_prerelease=False: update.Release(
            "0.1.0", "llmtop-0.1.0-py3-none-any.whl", "0" * 64
        ),
    )
    assert update.update_from_source(managed_install, SOURCE) is None
    assert not (managed_install / ".tmp").exists()


@pytest.mark.skipif(installer.sys.platform == "win32", reason="POSIX installer")
def test_update_from_wheel_offline(managed_install, wheel_020, monkeypatch):
    monkeypatch.setattr(installer, "checked", fake_checked("0.2.0"))
    receipt = update.update_from_wheel(managed_install, wheel_020)
    assert receipt["version"] == "0.2.0"
    assert receipt["source"] is None


@pytest.mark.skipif(installer.sys.platform == "win32", reason="POSIX installer")
def test_rollback_restores_previous(managed_install, wheel_020, monkeypatch):
    old = (managed_install / "current").resolve()
    digest = hashlib.sha256(wheel_020.read_bytes()).hexdigest()
    monkeypatch.setattr(
        update,
        "latest_release",
        lambda url, allow_prerelease=False: update.Release("0.2.0", wheel_020.name, digest),
    )
    monkeypatch.setattr(
        update, "download", lambda url, target, expected, cap: shutil.copyfile(wheel_020, target)
    )
    monkeypatch.setattr(installer, "checked", fake_checked("0.2.0"))
    updated = update.update_from_source(managed_install, SOURCE)
    rolled_back = update.rollback(managed_install)
    assert rolled_back["version"] == "0.1.0"
    assert rolled_back["previous_environment"] == updated["environment"]
    assert rolled_back["previous_version"] == "0.2.0"
    assert (managed_install / "current").resolve() == old


@pytest.mark.skipif(installer.sys.platform == "win32", reason="POSIX installer")
def test_rollback_without_previous(managed_install):
    with pytest.raises(update.UpdateError, match="No previous"):
        update.rollback(managed_install)


@pytest.mark.skipif(installer.sys.platform == "win32", reason="POSIX installer")
def test_update_refuses_when_lock_held(managed_install, wheel_020, monkeypatch):
    (managed_install / ".install.lock").write_text("")
    digest = hashlib.sha256(wheel_020.read_bytes()).hexdigest()
    monkeypatch.setattr(
        update,
        "latest_release",
        lambda url, allow_prerelease=False: update.Release("0.2.0", wheel_020.name, digest),
    )
    monkeypatch.setattr(
        update, "download", lambda url, target, expected, cap: shutil.copyfile(wheel_020, target)
    )
    monkeypatch.setattr(installer, "checked", fake_checked("0.2.0"))
    with pytest.raises(installer.InstallError, match="in progress"):
        update.update_from_source(managed_install, SOURCE)


def test_detect_install_root_rejects_unmanaged():
    assert update.detect_install_root() is None


@pytest.mark.skipif(installer.sys.platform == "win32", reason="POSIX installer")
def test_detect_install_root_finds_managed_layout(managed_install):
    assert update.detect_install_root(managed_install / "current" / "bin" / "python") == (
        managed_install.resolve()
    )
