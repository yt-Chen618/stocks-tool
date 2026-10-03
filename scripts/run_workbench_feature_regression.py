"""Run the professional workbench feature flow against an owned local mock server."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from browser_runtime import browser_environment, resolve_node, resolve_playwright_core
from regression_common import build_report, emit_report, run_bounded_process, start_utf8_process, stop_process, wait_for_http


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "workbench-feature-regression.json"
DEFAULT_SCREENSHOT_DIR = ROOT / "output" / "playwright" / "professional-workbench"
RESERVED_PORTS = {8765, 8786}
SOURCE_FILES = (
    Path("scripts/workbench_feature_browser_flow.js"),
    Path("scripts/run_workbench_feature_regression.py"),
    Path("scripts/browser_test_helpers.js"),
    Path("scripts/browser_runtime.py"),
    Path("scripts/regression_common.py"),
    Path("scripts/mock_dashboard_server.py"),
    Path("scripts/mock_dashboard_fixtures.py"),
    Path("scripts/mock_workbench_routes.py"),
    Path("scripts/mock_market_session_routes.py"),
    Path("src/stocks_tool/application/services/market_session_comparison.py"),
    Path("src/stocks_tool/domain/market_session_comparisons.py"),
    Path("src/stocks_tool/api/routes/ui.py"),
)


class RegressionError(RuntimeError):
    """A bounded feature regression failed."""


def allocate_free_port() -> int:
    """Return an available loopback port, excluding normal-gate reservations."""

    for _ in range(20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        if port not in RESERVED_PORTS:
            return port
    raise RegressionError("Could not allocate an isolated loopback port.")


def source_identity() -> dict[str, Any]:
    """Hash all loaded UI JS/CSS plus the flow, fixtures, and runtime helpers."""

    source_files = list(SOURCE_FILES)
    static_root = ROOT / "src" / "stocks_tool" / "ui" / "static"
    source_files.extend(
        path.relative_to(ROOT)
        for path in sorted(static_root.rglob("*"))
        if path.is_file() and path.suffix.lower() in {".js", ".css"}
    )
    digests: dict[str, str] = {}
    aggregate = hashlib.sha256()
    for relative in sorted(set(source_files), key=lambda value: str(value).replace("\\", "/")):
        path = ROOT / relative
        if not path.is_file():
            raise RegressionError(f"Source file for the evidence hash is missing: {relative}")
        normalized = str(relative).replace("\\", "/")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        digests[normalized] = digest
        aggregate.update(normalized.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(content)
        aggregate.update(b"\0")
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {
        "aggregate_sha256": aggregate.hexdigest(),
        "git_head": commit,
        "file_count": len(digests),
        "files": digests,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the real-DOM professional workbench feature flow against the in-memory "
            "paper-safe mock dashboard."
        )
    )
    parser.add_argument("--host", default="127.0.0.1", help="Mock server host.")
    parser.add_argument("--port", type=int, default=0, help="Mock server port; 0 allocates an isolated free port.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="Server and browser step timeout.")
    parser.add_argument("--browser-timeout-seconds", type=float, default=420.0, help="Finite timeout for the browser flow.")
    parser.add_argument("--json-output", default=str(DEFAULT_OUTPUT), help="Durable JSON report path.")
    parser.add_argument("--screenshot-dir", default=str(DEFAULT_SCREENSHOT_DIR), help="Responsive screenshot directory.")
    parser.add_argument("--keep-server", action="store_true", help="Leave the owned mock server running after completion.")
    return parser.parse_args()


def start_server(host: str, port: int) -> subprocess.Popen[str]:
    log_path = ROOT / "artifacts" / "mock-server-logs" / f"workbench-feature-{port}.log"
    return start_utf8_process(
        [
            sys.executable,
            str(ROOT / "scripts" / "mock_dashboard_server.py"),
            "--host",
            host,
            "--port",
            str(port),
            "--scenario",
            "normal",
        ],
        cwd=ROOT,
        output_log=log_path,
    )


def parse_browser_payload(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def run_browser_flow(
    base_url: str,
    *,
    screenshot_dir: Path,
    timeout_seconds: float,
    browser_timeout_seconds: float,
) -> dict[str, Any]:
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    completed = run_bounded_process(
        [
            resolve_node(),
            str(ROOT / "scripts" / "workbench_feature_browser_flow.js"),
            base_url,
            str(screenshot_dir),
            resolve_playwright_core(),
            str(int(timeout_seconds * 1000)),
        ],
        cwd=ROOT,
        env=browser_environment(),
        timeout_seconds=browser_timeout_seconds,
    )
    browser_payload = parse_browser_payload(completed.stdout)
    if completed.status != "completed" or completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "Unknown workbench browser failure."
        error = RegressionError(f"Workbench browser flow {completed.status}: {detail[-6000:]}")
        error.browser_payload = browser_payload
        error.process_status = "failed" if completed.status == "completed" else completed.status
        error.process_cleanup = completed.cleanup
        raise error
    if not browser_payload or browser_payload.get("rendered") is not True:
        error = RegressionError(f"Workbench browser flow did not emit rendered=true: {completed.stdout[-6000:]}")
        error.browser_payload = browser_payload
        error.process_status = "failed"
        raise error
    return browser_payload


def main() -> None:
    args = parse_args()
    if args.port in RESERVED_PORTS:
        raise SystemExit(f"Port {args.port} is reserved by an existing regression gate; choose another port.")
    port = args.port or allocate_free_port()
    base_url = f"http://{args.host}:{port}"
    identity_before = source_identity()
    server: subprocess.Popen[str] | None = None
    browser_payload: dict[str, Any] | None = None
    status = "passed"
    error_text: str | None = None
    cleanup: dict[str, Any] | None = None
    try:
        server = start_server(args.host, port)
        wait_for_http(f"{base_url}/", process=server, timeout_seconds=args.timeout_seconds)
        browser_payload = run_browser_flow(
            base_url,
            screenshot_dir=Path(args.screenshot_dir),
            timeout_seconds=args.timeout_seconds,
            browser_timeout_seconds=args.browser_timeout_seconds,
        )
    except Exception as error:
        status = getattr(error, "process_status", "failed")
        error_text = str(error)
        browser_payload = getattr(error, "browser_payload", browser_payload)
        cleanup = getattr(error, "process_cleanup", None)
    finally:
        if server is not None and not args.keep_server:
            try:
                cleanup = stop_process(server)
            except Exception as error:
                status = "cleanup_failed"
                error_text = f"{error_text}; server cleanup failed: {error}" if error_text else str(error)

    try:
        identity_after = source_identity()
    except Exception as error:
        identity_after = {"error": str(error)}
        status = "source_changed_during_gate"
        error_text = f"Source identity could not be captured after the gate: {error}"
    if isinstance(identity_after, dict) and identity_after.get("aggregate_sha256") != identity_before.get("aggregate_sha256"):
        status = "source_changed_during_gate"
        drift_detail = (
            "Source content changed during the browser gate: "
            f"before={identity_before.get('aggregate_sha256')} after={identity_after.get('aggregate_sha256')}"
        )
        error_text = f"{error_text}; {drift_detail}" if error_text else drift_detail

    payload: dict[str, Any] = {
        "port": port,
        "server": {"host": args.host, "process_cleanup": cleanup, "keep_server": args.keep_server},
        "source_identity_before": identity_before,
        "source_identity_after": identity_after,
        "browser": browser_payload or {},
    }
    report = build_report(
        script="run_workbench_feature_regression.py",
        workflow="professional-workbench-feature-dom",
        status=status,
        mode="mock",
        target=base_url,
        summary=(
            "Professional workbench research-to-strategy, portfolio, timeline, advisor, "
            "backtest, race, safety, and responsive DOM regression passed."
            if status == "passed"
            else "Professional workbench feature regression failed; inspect the durable browser payload and request audit."
        ),
        payload=payload,
        error=error_text,
    )
    emit_report(report, json_output=args.json_output)
    if status != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
