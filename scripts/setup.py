"""Prepare the desktop environment and start the host from a release package."""

from pathlib import Path
import argparse
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-only", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口须为 1024—65535")
    if sys.version_info < (3, 10):
        parser.error("需要 Python 3.10 或更新版本")
    sys.path.insert(0, str(ROOT))
    from web.core import Core

    core = Core()  # Missing or incompatible binaries fail before changing the environment.
    if not args.install_only:
        from web.session import open_running_service

        if open_running_service(Path(core.call("runtime-dir")["path"])):
            return
    python = ROOT / (
        ".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python"
    )
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True)
    subprocess.run(
        [str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")],
        check=True,
    )
    if not args.install_only:
        subprocess.run(
            [
                str(python),
                "-m",
                "web.server",
                "--open-browser",
                "--port",
                str(args.port),
            ],
            cwd=ROOT,
            check=True,
        )


if __name__ == "__main__":
    main()
