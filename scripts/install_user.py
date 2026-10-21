"""Install a built LLMTOP wheel for one Linux/macOS user, without root."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llmtop.installer import InstallError, install_wheel  # noqa: E402


def install(args: argparse.Namespace) -> dict:
    return install_wheel(
        wheel=args.wheel,
        root=args.install_dir,
        bin_dir=args.bin_dir,
        python=args.python,
        gpu=args.gpu,
        constraints=args.constraints,
        wheelhouse=args.wheelhouse,
        ensure_path=args.ensure_path,
    )


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
