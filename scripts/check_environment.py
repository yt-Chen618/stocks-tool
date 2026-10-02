"""Report the versions and missing pieces of the local regression environment.

This command only reads local metadata and inspects already-running services. It
never reads ``.env``, starts containers, installs packages, or opens a broker
connection.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.setup_environment import UV_VERSION, uv_candidate  # noqa: E402
REQUIRED_PYTHON_PACKAGES = (
    "alembic",
    "fastapi",
    "httpx",
    "longbridge",
    "psycopg",
    "pydantic-settings",
    "pytest",
    "sqlalchemy",
    "uvicorn",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only environment and dependency preflight for stocks-tool."
    )
    parser.add_argument("--json-output", type=Path, help="Write the report to this JSON path.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with status 1 when a required component is missing or mismatched.",
    )
    return parser.parse_args()


def run_command(
    command: Sequence[str],
    *,
    timeout: float = 10.0,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"returncode": None, "stdout": "", "stderr": str(error)}
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def command_path(*names: str) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def read_json(path: Path) -> dict[str, Any] | None:
    content = read_text(path)
    if content is None:
        return None
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def version_tuple(value: str | None) -> tuple[int, ...] | None:
    if not value:
        return None
    match = re.search(r"\d+(?:\.\d+){0,3}", value)
    if not match:
        return None
    return tuple(int(part) for part in match.group(0).split("."))


def exact_or_minor_match(actual: str | None, expected: str | None, *, minor: bool = False) -> bool:
    actual_tuple = version_tuple(actual)
    expected_tuple = version_tuple(expected)
    if actual_tuple is None or expected_tuple is None:
        return False
    return actual_tuple[: len(expected_tuple)] == expected_tuple if minor else actual_tuple == expected_tuple


def file_fingerprint(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def python_report(expected: str | None) -> dict[str, Any]:
    actual = ".".join(str(part) for part in sys.version_info[:3])
    return {
        "status": "ok" if exact_or_minor_match(actual, expected, minor=True) else "mismatch",
        "executable": str(Path(sys.executable).resolve()),
        "version": actual,
        "expected_minor": expected,
        "implementation": sys.implementation.name,
    }


def python_packages_report() -> dict[str, Any]:
    packages: dict[str, str | None] = {}
    for package in REQUIRED_PYTHON_PACKAGES:
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    missing = [package for package, version in packages.items() if version is None]
    return {
        "status": "ok" if not missing else "missing",
        "versions": packages,
        "missing": missing,
    }


def node_report(expected: str | None) -> dict[str, Any]:
    node = command_path("node.exe", "node")
    if node is None:
        return {"status": "missing", "executable": None, "version": None, "expected": expected}
    result = run_command([node, "--version"])
    version = result["stdout"] or None
    return {
        "status": "ok" if exact_or_minor_match(version, expected) else "mismatch",
        "executable": node,
        "version": version,
        "expected": expected,
        "stderr": result["stderr"] or None,
    }


def npm_report() -> dict[str, Any]:
    npm = command_path("npm.cmd", "npm")
    if npm is None:
        return {"status": "missing", "executable": None, "version": None}
    result = run_command([npm, "--version"])
    return {
        "status": "ok" if result["returncode"] == 0 else "failed",
        "executable": npm,
        "version": result["stdout"] or None,
    }


def playwright_report(node: str | None, expected: str | None) -> dict[str, Any]:
    package_json_path = ROOT / "node_modules" / "playwright" / "package.json"
    package_json = read_json(package_json_path)
    package_version = package_json.get("version") if package_json else None
    package_manifest = read_json(ROOT / "package.json") or {}
    expected_dev = (package_manifest.get("devDependencies") or {}).get("playwright")
    if package_version is None:
        return {
            "status": "missing",
            "version": None,
            "expected": expected or expected_dev,
            "package": str(package_json_path),
        }
    expected_version = expected or expected_dev
    return {
        "status": "ok" if package_version == expected_version else "mismatch",
        "version": package_version,
        "expected": expected_version,
        "package": str(package_json_path),
        "node_runtime": node,
        "lockfile": str(ROOT / "package-lock.json") if (ROOT / "package-lock.json").is_file() else None,
    }


def chromium_report(node: str | None) -> dict[str, Any]:
    if os.environ.get("PLAYWRIGHT_CHROME_PATH"):
        return {
            "status": "override", "version": None,
            "executable": os.environ["PLAYWRIGHT_CHROME_PATH"],
            "reproducible": False,
            "reason": "An explicit browser override bypasses the locked Chromium build.",
        }
    package_path = ROOT / "node_modules" / "playwright-core"
    package_json = package_path / "package.json"
    if node is None or not package_json.is_file():
        return {"status": "missing", "executable": None, "version": None}
    browser_env = dict(os.environ)
    browser_env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".playwright-browsers"))
    path_result = run_command(
        [
            node,
            "-e",
            "const {chromium}=require(process.argv[1]); process.stdout.write(chromium.executablePath());",
            str(package_path),
        ],
        env=browser_env,
    )
    executable = path_result["stdout"] or None
    if executable is None:
        return {"status": "missing", "executable": None, "version": None, "error": path_result["stderr"]}
    executable_path = Path(executable)
    if not executable_path.is_file():
        return {"status": "missing", "executable": executable, "version": None}
    version_result = run_command(
        [
            node,
            "-e",
            "const {chromium}=require(process.argv[1]); (async()=>{const browser=await chromium.launch({headless:true}); process.stdout.write(browser.version()); await browser.close();})().catch(error=>{console.error(error); process.exit(1);});",
            str(package_path),
        ],
        timeout=20.0,
        env=browser_env,
    )
    manifest = read_json(package_path / "browsers.json") or {}
    expected_version = next(
        (item.get("browserVersion") for item in manifest.get("browsers", []) if item.get("name") == "chromium"),
        None,
    )
    matched = bool(expected_version) and version_result["stdout"] == expected_version
    return {
        "status": "ok" if version_result["returncode"] == 0 and matched else "mismatch",
        "executable": executable,
        "version": version_result["stdout"] or None,
        "expected": expected_version,
        "stderr": version_result["stderr"] or None,
        "browsers_path": browser_env["PLAYWRIGHT_BROWSERS_PATH"],
        "reproducible": version_result["returncode"] == 0 and matched,
    }


def compose_image() -> str | None:
    content = read_text(ROOT / "compose.yaml")
    if content is None:
        return None
    match = re.search(r"^\s*image:\s*(postgres:[^\s#]+)", content, flags=re.MULTILINE)
    return match.group(1) if match else None


def postgres_report() -> dict[str, Any]:
    docker = command_path("docker.exe", "docker")
    configured_image = compose_image()
    report: dict[str, Any] = {
        "status": "missing" if docker is None else "unknown",
        "docker": docker,
        "configured_image": configured_image,
        "container": "stocks-tool-postgres",
        "container_status": None,
        "server_version": None,
        "image_id": None,
        "repo_digests": [],
    }
    if docker is None:
        return report
    inspect = run_command([docker, "inspect", "stocks-tool-postgres"])
    if inspect["returncode"] != 0:
        report["status"] = "missing"
        report["error"] = inspect["stderr"] or "PostgreSQL container is not present."
        return report
    try:
        container_data = json.loads(inspect["stdout"])[0]
    except (IndexError, json.JSONDecodeError, TypeError):
        report["status"] = "failed"
        report["error"] = "Docker returned an unreadable container inspection."
        return report
    report["container_status"] = (container_data.get("State") or {}).get("Status")
    report["image_id"] = container_data.get("Image")
    image_id = container_data.get("Image")
    if image_id:
        image_inspect = run_command([docker, "image", "inspect", image_id])
        if image_inspect["returncode"] == 0:
            try:
                image_data = json.loads(image_inspect["stdout"])[0]
                report["repo_digests"] = image_data.get("RepoDigests") or []
                report["image_created"] = image_data.get("Created")
                report["architecture"] = image_data.get("Architecture")
            except (IndexError, json.JSONDecodeError, TypeError):
                report["image_inspect_error"] = "Docker returned an unreadable image inspection."
    if report["container_status"] == "running":
        version = run_command([docker, "exec", "stocks-tool-postgres", "postgres", "--version"])
        report["server_version"] = version["stdout"] or None
        expected_version = version_tuple(configured_image)
        actual_version = version_tuple(report["server_version"])
        expected_digest = configured_image.split("@", 1)[1] if configured_image and "@" in configured_image else None
        digest_ok = expected_digest is not None and any(expected_digest in digest for digest in report["repo_digests"])
        version_ok = expected_version is not None and actual_version is not None and actual_version[:2] == expected_version[:2]
        report["digest_match"] = digest_ok
        report["version_match"] = version_ok
        report["status"] = "ok" if version_ok and digest_ok else "mismatch"
    else:
        report["status"] = "missing"
    return report


def alembic_report() -> dict[str, Any]:
    try:
        package_version = importlib.metadata.version("alembic")
    except importlib.metadata.PackageNotFoundError:
        return {"status": "missing", "version": None}
    result = run_command([sys.executable, "-m", "alembic", "--version"])
    return {
        "status": "ok" if result["returncode"] == 0 else "failed",
        "version": package_version,
        "command_output": result["stdout"] or None,
        "executable": str(Path(sys.executable).resolve()),
    }


def locked_environment_report() -> dict[str, Any]:
    executable = uv_candidate()
    if executable is None:
        return {"status": "missing", "version": None, "expected": UV_VERSION}
    version = run_command([executable, "--version"])
    if version["stdout"].split()[:2] != ["uv", UV_VERSION]:
        return {"status": "mismatch", "version": version["stdout"], "expected": UV_VERSION}
    environment = dict(os.environ)
    environment["UV_PROJECT_ENVIRONMENT"] = sys.prefix
    result = run_command(
        [executable, "sync", "--check", "--locked", "--extra", "dev", "--no-python-downloads", "--offline"],
        env=environment,
    )
    return {
        "status": "ok" if result["returncode"] == 0 else "mismatch",
        "version": version["stdout"],
        "environment": sys.prefix,
        "check": "uv sync --check --locked --extra dev --offline",
        "synchronized": result["returncode"] == 0,
    }


def schema_report() -> dict[str, Any]:
    """Read migration heads and an explicitly configured/already-running DB."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        configuration = Config(str(ROOT / "alembic.ini"))
        configuration.set_main_option("script_location", str(ROOT / "alembic"))
        heads = sorted(ScriptDirectory.from_config(configuration).get_heads())
    except Exception as error:
        return {"status": "unavailable", "error_type": type(error).__name__, "heads": []}
    current = []
    source = None
    if os.environ.get("DATABASE_URL"):
        try:
            from sqlalchemy import create_engine, text
            engine = create_engine(os.environ["DATABASE_URL"], connect_args={"connect_timeout": 5})
            try:
                with engine.connect() as connection:
                    current = sorted(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
            finally:
                engine.dispose()
            source = "DATABASE_URL (redacted)"
        except Exception as error:
            return {"status": "unavailable", "error_type": type(error).__name__, "heads": heads, "current": []}
    else:
        docker = command_path("docker.exe", "docker")
        if docker:
            result = run_command([
                docker, "exec", "stocks-tool-postgres", "sh", "-c",
                'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT version_num FROM alembic_version"',
            ])
            if result["returncode"] == 0:
                current = sorted(result["stdout"].splitlines())
                source = "existing stocks-tool-postgres container"
    return {
        "status": "ok" if len(heads) == 1 and current == heads else "mismatch",
        "heads": heads, "current": current, "source": source,
    }


def lock_report() -> dict[str, Any]:
    uv_lock = ROOT / "uv.lock"
    package_lock = ROOT / "package-lock.json"
    return {
        "status": "ok" if uv_lock.is_file() and package_lock.is_file() else "missing",
        "python_lock": {
            "path": str(uv_lock),
            "sha256": file_fingerprint(uv_lock),
        },
        "node_lock": {
            "path": str(package_lock),
            "sha256": file_fingerprint(package_lock),
        },
    }


def build_report() -> dict[str, Any]:
    expected_python = read_text(ROOT / ".python-version")
    expected_node = read_text(ROOT / ".node-version")
    node_path = command_path("node.exe", "node")
    components = {
        "python": python_report(expected_python),
        "python_packages": python_packages_report(),
        "node": node_report(expected_node),
        "npm": npm_report(),
        "playwright": playwright_report(node_path, None),
        "chromium": chromium_report(node_path),
        "postgres": postgres_report(),
        "alembic": alembic_report(),
        "locked_environment": locked_environment_report(),
        "schema": schema_report(),
        "locks": lock_report(),
    }
    required = tuple(components)
    failing = [name for name in required if components[name].get("status") != "ok"]
    fixes = {
        "python": "Use Python 3.12, then run python scripts/setup_environment.py.",
        "node": "Install the exact Node version declared in .node-version.",
        "npm": "Install npm with the Node version declared in .node-version.",
        "postgres": "Start the pinned service with docker compose up -d --wait db.",
        "schema": "Back up an existing database, then run the locked environment's python -m alembic upgrade head.",
        "locks": "Restore committed uv.lock and package-lock.json before installing.",
        "chromium": "Run python scripts/setup_environment.py and clear PLAYWRIGHT_CHROME_PATH for the reproducible browser gate.",
    }
    for name in failing:
        components[name]["next_action"] = fixes.get(name, "Run python scripts/setup_environment.py, then use the resulting virtual environment.")
    return {
        "script": "check_environment.py",
        "workflow": "environment-preflight",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "status": "passed" if not failing else "attention",
        "missing_or_mismatched": failing,
        "components": components,
    }


def main() -> int:
    args = parse_args()
    report = build_report()
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if not args.strict or report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
