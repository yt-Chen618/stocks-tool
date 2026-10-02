"""Create the reproducible local development and browser-gate environment."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
UV_VERSION = "0.12.22"
VENV = ROOT / ".venv"
BROWSER_CACHE = ROOT / ".playwright-browsers"


class SetupError(RuntimeError):
    """Raised when a required reproducible setup step cannot complete."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Set up the repository's locked Python dependencies, project-local Node "
            "dependencies, and Chromium runtime."
        )
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="Install Node dependencies without downloading Chromium.",
    )
    parser.add_argument(
        "--start-postgres",
        action="store_true",
        help="Start the pinned local PostgreSQL service after installing dependencies.",
    )
    parser.add_argument(
        "--no-bootstrap-uv",
        action="store_true",
        help="Fail if uv is not already available instead of installing the pinned bootstrap tool.",
    )
    parser.add_argument(
        "--python-environment",
        type=Path,
        default=VENV,
        help="Virtual environment path (default: repository .venv).",
    )
    parser.add_argument(
        "--browser-cache",
        type=Path,
        default=BROWSER_CACHE,
        help="Playwright browser cache path (default: repository .playwright-browsers).",
    )
    return parser.parse_args()


def command_path(*names: str) -> str | None:
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def run(command: Sequence[str], *, env: dict[str, str] | None = None) -> None:
    rendered = " ".join(command)
    print(f"$ {rendered}")
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if completed.returncode:
        raise SetupError(f"Setup command failed ({completed.returncode}): {rendered}")


def user_scripts_directory() -> Path:
    scheme = sysconfig.get_preferred_scheme("user")
    return Path(sysconfig.get_path("scripts", scheme=scheme))


def uv_candidate() -> str | None:
    candidate = command_path("uv.exe", "uv")
    if candidate:
        return candidate
    user_candidate = user_scripts_directory() / ("uv.exe" if os.name == "nt" else "uv")
    return str(user_candidate) if user_candidate.is_file() else None


def check_uv_version(executable: str) -> None:
    result = subprocess.run([executable, "--version"], check=True, capture_output=True, text=True)
    if result.stdout.split()[:2] != ["uv", UV_VERSION]:
        raise SetupError(
            f"uv {UV_VERSION} is required; found {result.stdout.strip()}. "
            f"Install uv=={UV_VERSION} using the base Python interpreter."
        )


def ensure_uv(*, allow_bootstrap: bool) -> str:
    existing = uv_candidate()
    if existing:
        check_uv_version(existing)
        return existing
    if not allow_bootstrap:
        raise SetupError(
            f"uv {UV_VERSION} is required. Install it or omit --no-bootstrap-uv to bootstrap it."
        )
    run(
        [
            getattr(sys, "_base_executable", None) or sys.executable,
            "-m",
            "pip",
            "install",
            "--user",
            "--disable-pip-version-check",
            f"uv=={UV_VERSION}",
        ]
    )
    candidate = user_scripts_directory() / ("uv.exe" if os.name == "nt" else "uv")
    if not candidate.is_file():
        raise SetupError(f"uv installation completed but the executable was not found at {candidate}")
    check_uv_version(str(candidate))
    return str(candidate)


def require_python() -> None:
    if sys.version_info < (3, 11):
        raise SetupError(
            f"Python 3.11 or newer is required; this interpreter is {sys.version.split()[0]}. "
            "Use the minor version declared in .python-version."
        )


def require_node() -> str:
    node = command_path("node.exe", "node")
    if node is None:
        raise SetupError(
            "Node.js is required for the browser gate. Install the version declared in .node-version."
        )
    expected = (ROOT / ".node-version").read_text(encoding="utf-8").strip()
    actual = subprocess.run([node, "--version"], check=True, capture_output=True, text=True).stdout.strip().lstrip("v")
    if actual != expected:
        raise SetupError(f"Node.js {expected} is required; found {actual}. Use .node-version before setup.")
    return node


def require_npm() -> str:
    npm = command_path("npm.cmd", "npm")
    if npm is None:
        raise SetupError("npm is required for the project-local Playwright install.")
    return npm


def install_python(uv: str, environment: Path) -> None:
    env = dict(os.environ)
    env["UV_PROJECT_ENVIRONMENT"] = str(environment)
    if os.name == "nt":
        env.setdefault("UV_SYSTEM_CERTS", "true")
    run([uv, "sync", "--locked", "--extra", "dev"], env=env)


def install_node(npm: str, *, skip_browser: bool, browser_cache: Path) -> None:
    run([npm, "ci", "--ignore-scripts"])
    if skip_browser:
        return
    playwright = ROOT / "node_modules" / ".bin" / ("playwright.cmd" if os.name == "nt" else "playwright")
    if not playwright.is_file():
        raise SetupError("npm ci completed but the local Playwright executable is missing.")
    env = dict(os.environ)
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_cache)
    run([str(playwright), "install", "chromium"], env=env)


def start_postgres() -> None:
    docker = command_path("docker.exe", "docker")
    if docker is None:
        raise SetupError("--start-postgres requires Docker Desktop/Engine on PATH.")
    run([docker, "compose", "up", "-d", "--wait", "db"])


def main() -> int:
    args = parse_args()
    require_python()
    uv = ensure_uv(allow_bootstrap=not args.no_bootstrap_uv)
    node = require_node()
    npm = require_npm()
    install_python(uv, args.python_environment)
    install_node(npm, skip_browser=args.skip_browser, browser_cache=args.browser_cache)
    if args.start_postgres:
        start_postgres()
    environment_python = args.python_environment / (
        "Scripts\\python.exe" if os.name == "nt" else "bin/python"
    )
    print(
        "Environment setup completed. Run scripts/check_environment.py for a read-only "
        f"version and missing-component report. Python={environment_python}; Node={node}; uv={uv}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SetupError as error:
        print(f"setup_environment: {error}", file=sys.stderr)
        raise SystemExit(1) from error
