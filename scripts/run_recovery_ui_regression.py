from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from browser_runtime import browser_environment, resolve_node, resolve_playwright_core
from regression_common import build_report, emit_report, run_bounded_process
from run_mock_ui_order_regression import RegressionError, start_server, stop_server, wait_for_server


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 8765
DEFAULT_OUTPUT = ROOT / "artifacts" / "recovery-ui-regression.json"
DEFAULT_SCREENSHOT_DIR = ROOT / "output" / "playwright" / "recovery-ui"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the read-only Operations recovery panel against the local mock dashboard "
            "with real Playwright DOM checks."
        )
    )
    parser.add_argument("--host", default="127.0.0.1", help="Mock server host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Mock server port.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="Server and browser step timeout.")
    parser.add_argument("--browser-timeout-seconds", type=float, default=300.0, help="Finite timeout for the browser flow.")
    parser.add_argument("--json-output", default=str(DEFAULT_OUTPUT), help="JSON report path.")
    parser.add_argument("--screenshot-dir", default=str(DEFAULT_SCREENSHOT_DIR), help="Screenshot output directory.")
    parser.add_argument("--keep-server", action="store_true", help="Leave the mock server running after the script exits.")
    return parser.parse_args()


def run_browser_flow(
    base_url: str,
    *,
    screenshot_dir: Path,
    timeout_seconds: float,
    browser_timeout_seconds: float,
) -> dict[str, Any]:
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    node = resolve_node()
    playwright_core = resolve_playwright_core()
    completed = run_bounded_process(
        [
            node,
            str(ROOT / "scripts" / "recovery_ui_browser_flow.js"),
            base_url,
            str(screenshot_dir),
            playwright_core,
            str(int(timeout_seconds * 1000)),
        ],
        cwd=ROOT,
        env=browser_environment(),
        timeout_seconds=browser_timeout_seconds,
    )
    if completed.status != "completed" or completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "Unknown recovery UI browser failure."
        error = RegressionError(f"Recovery browser flow {completed.status}: {detail}")
        error.process_status = completed.status
        error.process_cleanup = completed.cleanup
        raise error
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RegressionError(
            f"Recovery UI browser output was not valid JSON: {completed.stdout}"
        ) from error


def main() -> None:
    args = parse_args()
    base_url = f"http://{args.host}:{args.port}"
    server = start_server(args.host, args.port, scenario="normal")
    try:
        wait_for_server(f"{base_url}/", args.timeout_seconds, server)
        browser = run_browser_flow(
            base_url,
            screenshot_dir=Path(args.screenshot_dir),
            timeout_seconds=args.timeout_seconds,
            browser_timeout_seconds=args.browser_timeout_seconds,
        )
        if not browser.get("rendered"):
            raise RegressionError("Recovery UI browser flow did not report rendered=true.")
        if browser.get("mutation_requests"):
            raise RegressionError(
                f"Recovery UI flow observed broker mutation requests: {browser['mutation_requests']}"
            )
        emit_report(
            build_report(
                script="run_recovery_ui_regression.py",
                workflow="mock-recovery-ui-dom",
                status="passed",
                mode="mock",
                target=base_url,
                summary=(
                    "Recovery Operations panel passed real DOM checks for blocking evidence, "
                    "pagination, account races, language switching, and read-only failure posture."
                ),
                payload=browser,
            ),
            json_output=args.json_output,
        )
    except Exception as error:
        emit_report(
            build_report(
                script="run_recovery_ui_regression.py",
                workflow="mock-recovery-ui-dom",
                    status=getattr(error, "process_status", "failed"),
                mode="mock",
                target=base_url,
                summary="Recovery Operations DOM regression failed.",
                error=str(error),
            ),
            json_output=args.json_output,
        )
        raise
    finally:
        if not args.keep_server:
            stop_server(server)


if __name__ == "__main__":
    main()
