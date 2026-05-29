from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from regression_common import build_report, emit_report

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 8765


class RegressionError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a mock dashboard regression against a local in-memory backend. "
            "This validates the rendered dashboard shell plus submit/replace/cancel order flow "
            "without touching the real paper account."
        )
    )
    parser.add_argument("--host", default="127.0.0.1", help="Mock server host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Mock server port.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="HTTP timeout and step deadline.")
    parser.add_argument("--poll-seconds", type=float, default=0.5, help="Polling interval for mock state checks.")
    parser.add_argument("--keep-server", action="store_true", help="Leave the mock server running after the script exits.")
    parser.add_argument("--json-output", help="Optional file path for the JSON regression report.")
    return parser.parse_args()


def start_server(host: str, port: int) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts" / "mock_dashboard_server.py"),
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def stop_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def wait_for_server(base_url: str, timeout_seconds: float, process: subprocess.Popen[str]) -> None:
    deadline = time.time() + timeout_seconds
    last_error: str | None = None
    while time.time() < deadline:
        if process.poll() is not None:
            output = ""
            if process.stdout is not None:
                output = process.stdout.read()
            raise RegressionError(f"Mock server exited early.\nServer output:\n{output}")
        try:
            response = httpx.get(base_url, timeout=2.0)
            if response.status_code == 200:
                return
        except Exception as error:  # pragma: no cover - transient bootstrap noise
            last_error = str(error)
        time.sleep(0.25)
    raise RegressionError(f"Mock server did not become ready at {base_url}: {last_error}")


def require_ok(response: httpx.Response) -> Any:
    if response.is_success:
        return response.json()
    detail = f"HTTP {response.status_code}"
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and payload.get("detail"):
        detail = str(payload["detail"])
    raise RegressionError(detail)


def resolve_playwright_core() -> str:
    npm_command = shutil.which("npm.cmd") or shutil.which("npm")
    if npm_command is None:
        raise RegressionError("Could not find npm. Install Node.js/npm before running browser regression.")
    npm_root = subprocess.run(
        [npm_command, "root", "-g"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    candidates = [
        Path(npm_root) / "@playwright" / "cli" / "node_modules" / "playwright-core",
        Path(npm_root) / "playwright-core",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise RegressionError(
        "Could not locate a global playwright-core install. Install @playwright/cli and browsers first."
    )


def run_browser_flow(base_url: str) -> dict[str, Any]:
    screenshot_path = ROOT / "output" / "playwright" / "mock-ui-browser-regression.png"
    playwright_core_path = resolve_playwright_core()
    node_command = shutil.which("node.exe") or shutil.which("node")
    if node_command is None:
        raise RegressionError("Could not find node. Install Node.js before running browser regression.")
    completed = subprocess.run(
        [
            node_command,
            str(ROOT / "scripts" / "mock_ui_browser_flow.js"),
            base_url,
            str(screenshot_path),
            playwright_core_path,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ},
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "Unknown browser regression failure."
        raise RegressionError(detail)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RegressionError(f"Browser regression output was not valid JSON: {completed.stdout}") from error


def main() -> None:
    args = parse_args()
    base_url = f"http://{args.host}:{args.port}"
    server = start_server(args.host, args.port)

    try:
        wait_for_server(f"{base_url}/", args.timeout_seconds, server)
        client = httpx.Client(base_url=base_url, timeout=args.timeout_seconds)
        try:
            dashboard = client.get("/")
            dashboard.raise_for_status()
            assert "Strategy Center" in dashboard.text
            assert "Holdings Overview" in dashboard.text
            assert "Real-time Macro Board" in dashboard.text
            assert "Load Live Macro" in dashboard.text
            assert "Load Option Overlays" in dashboard.text
            assert "Save Current Board" in dashboard.text
            assert "Risk Proxies" in dashboard.text
            assert "QQQ / SPY Put Check" in dashboard.text
            assert "Stored Opening Follow-through" in dashboard.text
            assert "Bull Put Strategy" in dashboard.text
            assert "Latest Skip Reason" in dashboard.text
            assert "Latest Review" in dashboard.text
            assert "Bull Put Monitor" in dashboard.text
            assert "Execution Desk" in dashboard.text
            assert "Order Ticket" in dashboard.text
            assert "Selected Order" in dashboard.text
            assert "Execution Summary" in dashboard.text
            assert "Review Workflow" in dashboard.text
            assert "Orders" in dashboard.text
            assert "Watchlists" not in dashboard.text
            assert "Longbridge Status" not in dashboard.text
            assert "Quick Quote" not in dashboard.text

            app_js = client.get("/static/app.js")
            app_js.raise_for_status()
            for marker in (
                "order-ticket-form",
                "replace-order-form",
                "selected-order-card",
                "selected-order-execution",
                "journal-entry-form",
                "selected-order-journal",
                "strategy-runtime-strip",
                "preopen-summary-strip",
                "preopen-assessment-card",
                "preopen-run-review",
                "LANGUAGE_STORAGE_KEY",
                "prepareMarketOverlayPanels()",
                "renderPreOpenAssessment(",
                "renderLatestPreOpenRun()",
                "saveCurrentPreOpenBoard()",
                "strategy-controls-form",
                "runStrategyScan()",
                "runStrategyReview()",
                "saveStrategyControls()",
                "renderStrategyRuntime()",
                "spread-summary-strip",
                "spreads-body",
                "submitOrder()",
                "submitJournalEntry()",
                "replaceSelectedOrder()",
                "renderSpreads()",
                "monitorSpread(",
                "renderSelectedExecution()",
                "renderSelectedJournal()",
            ):
                assert marker in app_js.text

            accounts = require_ok(client.get("/broker-accounts"))
            assert accounts[0]["external_account_id"] == "LBPT10087357"
            assert accounts[0]["auto_reconcile_enabled"] is True
            pre_open = require_ok(client.get("/strategies/pre-open-risk"))
            assert pre_open["preferred_vehicle"] == "QQQ"
            assert pre_open["plain_put_view"] == "reasonable"
            pre_open_runs = require_ok(
                client.get("/strategies/pre-open-runs", params={"external_account_id": "LBPT10087357", "limit": 1})
            )
            assert len(pre_open_runs) == 1
            assert pre_open_runs[0]["review_status"] == "confirmed"

            snapshots = require_ok(client.get("/account-snapshots", params={"external_account_id": "LBPT10087357"}))
            assert snapshots[0]["positions"][0]["symbol"] == "MOCK.US"

            initial_orders = require_ok(client.get("/orders", params={"external_account_id": "LBPT10087357"}))
            assert len(initial_orders) == 2
            initial_spreads = require_ok(client.get("/strategies/bull-put/spreads", params={"external_account_id": "LBPT10087357"}))
            assert len(initial_spreads) == 1
            assert initial_spreads[0]["status"] == "open"
            runtime_state = require_ok(
                client.get("/strategies/bull-put/runtime", params={"external_account_id": "LBPT10087357"})
            )
            assert runtime_state["auto_entry_enabled"] is True
            assert runtime_state["kill_switch_active"] is False
            initial_executions = require_ok(client.get("/executions", params={"external_account_id": "LBPT10087357"}))
            assert len(initial_executions) == 1
            assert initial_executions[0]["order_id"] == "mock-order-0002"
            initial_journals = require_ok(client.get("/journals", params={"external_account_id": "LBPT10087357"}))
            assert len(initial_journals) == 1
            assert initial_journals[0]["order_id"] == "mock-order-0002"
            browser = run_browser_flow(base_url)

            emit_report(
                build_report(
                    script="run_mock_ui_order_regression.py",
                    workflow="mock-dashboard-order-regression",
                    status="passed",
                    mode="mock",
                    target=base_url,
                    summary="Mock dashboard shell plus browser-driven order, spread, and journal workflows passed.",
                    payload={
                        "checks": {
                            "dashboard_shell": True,
                            "pre_open_shell": True,
                            "pre_open_review_shell": True,
                            "bull_put_shell": True,
                            "execution_summary_shell": True,
                            "pre_open_seed": True,
                            "pre_open_run_seed": True,
                            "app_js_markers": True,
                            "account_seed": True,
                            "snapshot_seed": True,
                            "runtime_seed": True,
                            "spread_seed": True,
                            "execution_seed": True,
                            "journal_seed": True,
                            "browser_flow": True,
                        },
                        "browser": browser,
                    },
                ),
                json_output=args.json_output,
            )
        finally:
            client.close()
    except Exception as error:
        emit_report(
            build_report(
                script="run_mock_ui_order_regression.py",
                workflow="mock-dashboard-order-regression",
                status="failed",
                mode="mock",
                target=base_url,
                summary="Mock dashboard regression failed.",
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
