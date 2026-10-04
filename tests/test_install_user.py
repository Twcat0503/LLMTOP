import argparse
import json
import zipfile
from pathlib import Path

import pytest

from scripts import install_user


@pytest.fixture
def wheel(tmp_path):
    result = tmp_path / "llmtop-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(result, "w") as archive:
        archive.writestr("llmtop-0.1.0.dist-info/METADATA", "Name: llmtop\nVersion: 0.1.0\n")
        archive.writestr("llmtop/web_static/index.html", "<!doctype html>")
        archive.writestr("llmtop/web_static/build-info.json", '{"version":"0.1.0"}')
        archive.writestr("llmtop/web_static/assets/app.js", "console.log('synthetic fixture')")
    return result


def test_wheel_must_include_web_assets(tmp_path):
    wheel = tmp_path / "incomplete.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("llmtop-0.1.0.dist-info/METADATA", "Name: llmtop\nVersion: 0.1.0\n")
    with pytest.raises(install_user.InstallError, match="Web assets"):
        install_user.wheel_version(wheel)


def test_wheel_refuses_mismatched_web_version(tmp_path):
    wheel = tmp_path / "mismatched.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("llmtop-0.1.0.dist-info/METADATA", "Name: llmtop\nVersion: 0.1.0\n")
        archive.writestr("llmtop/web_static/index.html", "<!doctype html>")
        archive.writestr("llmtop/web_static/assets/app.js", "// fixture")
        archive.writestr("llmtop/web_static/build-info.json", '{"version":"0.2.0"}')
    with pytest.raises(install_user.InstallError, match="do not match"):
        install_user.wheel_version(wheel)


def test_path_setup_preserves_profile_and_is_idempotent(tmp_path):
    profile = tmp_path / ".profile"
    profile.write_text("# User settings\nexport EXAMPLE=1\n")
    bin_dir = tmp_path / "bin with spaces"
    changes = install_user.profile_changes(bin_dir, tmp_path, "bash")
    for path, addition in changes.items():
        with path.open("a") as output:
            output.write(addition)
    assert profile.read_text().startswith("# User settings\nexport EXAMPLE=1\n")
    assert not install_user.profile_changes(bin_dir, tmp_path, "bash")
    with pytest.raises(install_user.InstallError, match="different"):
        install_user.profile_changes(tmp_path / "other-bin", tmp_path, "bash")


@pytest.mark.skipif(install_user.sys.platform == "win32", reason="POSIX installer")
def test_failed_install_preserves_active_environment_and_config(tmp_path, wheel, monkeypatch):
    root = tmp_path / "installation"
    old = root / "environments/old"
    old.mkdir(parents=True)
    (root / "current").symlink_to(old)
    (root / install_user.MARKER).write_text(
        json.dumps({"kind": "llmtop-user-install", "schema_version": 1})
    )
    private_config = tmp_path / "settings.toml"
    private_config.write_text("# User configuration\n")
    args = argparse.Namespace(
        wheel=wheel,
        install_dir=root,
        bin_dir=tmp_path / "bin",
        ensure_path=False,
        python="python3",
        wheelhouse=None,
        constraints=None,
        gpu=False,
    )

    def failed(command, root, environment):
        Path(command[-1]).mkdir(parents=True)
        raise install_user.InstallError("Synthetic installation failure")

    monkeypatch.setattr(install_user, "checked", failed)
    with pytest.raises(install_user.InstallError, match="Synthetic"):
        install_user.install(args)
    assert (root / "current").resolve() == old
    assert list((root / "environments").iterdir()) == [old]
    assert private_config.read_text() == "# User configuration\n"
    assert not (root / ".install.lock").exists()


@pytest.mark.skipif(install_user.sys.platform == "win32", reason="POSIX installer")
def test_install_refuses_unrelated_directory_and_launcher(tmp_path, wheel):
    root = tmp_path / "unrelated"
    root.mkdir()
    original = root / "keep.txt"
    original.write_text("Keep this file")
    args = argparse.Namespace(
        wheel=wheel, install_dir=root, bin_dir=tmp_path / "bin", ensure_path=False
    )
    with pytest.raises(install_user.InstallError, match="unrelated files"):
        install_user.install(args)
    assert original.read_text() == "Keep this file"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "llmtop").write_text("Unrelated program")
    with pytest.raises(install_user.InstallError, match="unrelated llmtop"):
        install_user.install(args)
    assert (bin_dir / "llmtop").read_text() == "Unrelated program"
