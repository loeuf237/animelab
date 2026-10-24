"""Run the same checks locally and in CI, without using the personal library."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence

ROOT = Path(__file__).resolve().parents[1]


def run(command: Sequence[str], *, frontend: bool = False, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT / "frontend" if frontend else ROOT, env=env, check=True)


def test_environment(directory: Path) -> dict[str, str]:
    # Remove personal source/proxy/settings overrides before importing the engine.
    env = {key: value for key, value in os.environ.items() if not key.startswith("ANIMAN_")}
    home = directory / "home"
    home.mkdir()
    scratch = directory / "tmp"
    scratch.mkdir()
    env.update({
        "HOME": str(home),
        "USERPROFILE": str(home),
        "TMPDIR": str(scratch),
        "TEMP": str(scratch),
        "TMP": str(scratch),
        "ANIMAN_DB_PATH": str(directory / "library.sqlite3"),
        "ANIMAN_DOWNLOAD_DIR": str(directory / "downloads"),
        "ANIMAN_CACHE_DIR": str(directory / "cache"),
        "ANIMAN_STARTUP_REFRESH": "false",
        "ANIMAN_HOST": "127.0.0.1",
        "ANIMAN_ALLOWED_HOSTS": "localhost,127.0.0.1,testserver,test",
        "ANIMAN_RELOAD": "false",
        "TMDB_API_KEY": "",
    })
    return env


def python_tests(pytest_args: list[str]) -> None:
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise SystemExit("Build the interface first: cd frontend && npm ci && npm run build")
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise SystemExit("Install system prerequisites on PATH: " + ", ".join(missing))
    with tempfile.TemporaryDirectory(prefix="animelab-tests-") as directory:
        run([sys.executable, "-m", "pytest", "tests", "-q", *pytest_args],
            env=test_environment(Path(directory)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=("quality", "python", "frontend", "ui", "all"))
    args, extra = parser.parse_known_args()
    if extra and args.check != "python":
        parser.error("Extra pytest arguments are only supported by the python check")
    npm = shutil.which("npm") or "npm"
    if args.check in ("quality", "all"):
        run([sys.executable, "-m", "ruff", "check", "."])
        run([sys.executable, "-m", "mypy"])
        run([npm, "run", "lint"], frontend=True)
        run([npm, "run", "format:check"], frontend=True)
        run([npm, "run", "typecheck"], frontend=True)
    if args.check in ("frontend", "all"):
        run([npm, "test"], frontend=True)
        run([npm, "run", "build"], frontend=True)
    if args.check in ("python", "all"):
        python_tests(extra)
    if args.check in ("ui", "all"):
        run([npm, "run", "test:ui"], frontend=True)


if __name__ == "__main__":
    main()
