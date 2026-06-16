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
MOCK_SCENARIOS = (
    "normal",
    "degraded-broker",
    "paused-mandate",
    "advisor-pending-record",
    "manual-action-required",
    "scheduler-backoff",
    "recover-eligible",
    "recover-rejected",
    "recover-already-working",
)


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
    parser.add_argument(
        "--scenario",
        choices=(*MOCK_SCENARIOS, "all"),
        default="normal",
        help="Mock posture scenario to run, or all for the full posture matrix.",
    )
    return parser.parse_args()


def start_server(host: str, port: int, *, scenario: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts" / "mock_dashboard_server.py"),
            "--host",
            host,
            "--port",
            str(port),
            "--scenario",
            scenario,
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


def run_scenario_assertions(client: httpx.Client, *, scenario: str) -> dict[str, Any]:
    operator_status = require_ok(
        client.get("/ops/unattended-status", params={"external_account_id": "LBPT10087357", "mode": "paper"})
    )
    audit_events = require_ok(client.get("/ops/audit", params={"external_account_id": "LBPT10087357"}))
    audit_summary = require_ok(
        client.get("/ops/audit/summary", params={"external_account_id": "LBPT10087357", "mode": "paper"})
    )
    spreads = require_ok(client.get("/strategies/bull-put/spreads", params={"external_account_id": "LBPT10087357"}))
    recovery_eligibility = (
        require_ok(
            client.get(
                f"/strategies/bull-put/spreads/{spreads[0]['id']}/recover-close/eligibility",
                params={"external_account_id": "LBPT10087357", "mode": "paper"},
            )
        )
        if spreads
        else None
    )
    advisor_run_cards = require_ok(
        client.get(
            "/strategies/advisor/run-cards",
            params={"external_account_id": "LBPT10087357", "source": "deepseek"},
        )
    )
    evidence = {
        "scenario": scenario,
        "operator_status": operator_status.get("status"),
        "operator_posture_reason": operator_status.get("operator_posture_reason"),
        "reason_codes": [
            check.get("reason_code")
            for check in operator_status.get("checks", [])
            if isinstance(check, dict) and check.get("reason_code")
        ],
        "audit_actions": [event.get("action") for event in audit_events],
        "audit_warning_codes": [event.get("warning_code") for event in audit_events if event.get("warning_code")],
        "audit_summary_groups": len(audit_summary.get("groups") or []) if isinstance(audit_summary, dict) else None,
        "recover_close_eligibility": recovery_eligibility,
        "advisor_recorded": advisor_run_cards[0].get("recorded") if advisor_run_cards else None,
    }
    if scenario == "degraded-broker":
        profiles = operator_status.get("broker_profiles") or []
        assert profiles and profiles[0]["credential_status"] == "degraded"
    elif scenario == "paused-mandate":
        mandate = operator_status.get("paper_mandate") or {}
        assert mandate.get("manual_pause") is True
        assert "manual_pause" in (mandate.get("reason_codes") or [])
    elif scenario == "advisor-pending-record":
        assert advisor_run_cards and advisor_run_cards[0]["recorded"] is False
        assert "advisor_pending_record" in evidence["audit_warning_codes"]
    elif scenario == "manual-action-required":
        assert operator_status.get("lifecycle_warnings")
        assert "manual_action_required" in evidence["reason_codes"]
    elif scenario == "scheduler-backoff":
        summaries = operator_status.get("recent_scheduler_summaries") or []
        assert summaries and summaries[0]["due_status"] == "backoff"
        assert "scheduler_backoff" in evidence["reason_codes"]
    elif scenario == "recover-eligible":
        assert recovery_eligibility and recovery_eligibility["eligible"] is True
        assert recovery_eligibility["old_short_close_order_status"] == "canceled"
    elif scenario == "recover-rejected":
        assert recovery_eligibility and recovery_eligibility["eligible"] is False
        assert "close_not_required" in recovery_eligibility["reasons"]
    elif scenario == "recover-already-working":
        assert recovery_eligibility and recovery_eligibility["eligible"] is False
        assert recovery_eligibility["working_replacement_order_id"] == "mock-order-0001"
        assert "working_replacement_exists" in recovery_eligibility["reasons"]
    else:
        assert operator_status["paper_mandate"]["external_account_id"] == "LBPT10087357"
        assert operator_status["audit_summary"]["event_count"] >= 1
    return evidence


def main() -> None:
    args = parse_args()
    if args.scenario == "all":
        scenario_reports: list[dict[str, Any]] = []
        for scenario in MOCK_SCENARIOS:
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--host",
                args.host,
                "--port",
                str(args.port),
                "--timeout-seconds",
                str(args.timeout_seconds),
                "--poll-seconds",
                str(args.poll_seconds),
                "--scenario",
                scenario,
            ]
            completed = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                detail = completed.stderr.strip() or completed.stdout.strip() or f"Scenario {scenario} failed."
                raise RegressionError(detail)
            try:
                scenario_reports.append(json.loads(completed.stdout))
            except json.JSONDecodeError as error:
                raise RegressionError(f"Scenario {scenario} did not emit JSON evidence: {completed.stdout}") from error
        emit_report(
            build_report(
                script="run_mock_ui_order_regression.py",
                workflow="mock-dashboard-scenario-matrix",
                status="passed",
                mode="mock",
                target=f"http://{args.host}:{args.port}",
                summary="Mock dashboard posture scenario matrix passed.",
                payload={"scenarios": scenario_reports},
            ),
            json_output=args.json_output,
        )
        return

    base_url = f"http://{args.host}:{args.port}"
    server = start_server(args.host, args.port, scenario=args.scenario)

    try:
        wait_for_server(f"{base_url}/", args.timeout_seconds, server)
        client = httpx.Client(base_url=base_url, timeout=args.timeout_seconds)
        try:
            if args.scenario != "normal":
                evidence = run_scenario_assertions(client, scenario=args.scenario)
                emit_report(
                    build_report(
                        script="run_mock_ui_order_regression.py",
                        workflow=f"mock-dashboard-{args.scenario}",
                        status="passed",
                        mode="mock",
                        target=base_url,
                        summary=f"Mock dashboard posture scenario '{args.scenario}' passed.",
                        payload={"scenario": args.scenario, "evidence": evidence},
                    ),
                    json_output=args.json_output,
                )
                return

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
            assert "Lottery Strategy" in dashboard.text
            assert "Preview Lottery" in dashboard.text
            assert "Force Scan" in dashboard.text
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
                "strategy-experiment-strip",
                "market-events-card",
                "preopen-summary-strip",
                "preopen-assessment-card",
                "preopen-run-review",
                "LANGUAGE_STORAGE_KEY",
                "prepareMarketOverlayPanels()",
                "renderPreOpenAssessment(",
                "renderLatestPreOpenRun()",
                "saveCurrentPreOpenBoard()",
                "strategy-controls-form",
                "zero-dte-lottery-controls-form",
                "previewZeroDteLottery()",
                "runZeroDteLotteryScan()",
                "zero-dte-lottery/runtime",
                "runStrategyScan()",
                "runStrategyReview()",
                "saveStrategyControls()",
                "reconcileCoveredCallLifecycle()",
                "covered-call/lifecycle",
                "Refresh Lifecycle",
                "renderCoveredCallLatestMonitor(",
                "Latest Monitor",
                "renderStrategyRuntime()",
                "renderStrategyExperiment()",
                "renderMarketEvents()",
                "spread-summary-strip",
                "spreads-body",
                "submitOrder()",
                "submitJournalEntry()",
                "replaceSelectedOrder()",
                "renderSpreads()",
                "monitorSpread(",
                "recoverCloseSpread(",
                "recover-close/eligibility",
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
            recovery_eligibility = require_ok(
                client.get(
                    f"/strategies/bull-put/spreads/{initial_spreads[0]['id']}/recover-close/eligibility",
                    params={"external_account_id": "LBPT10087357", "mode": "paper"},
                )
            )
            assert "eligible" in recovery_eligibility
            runtime_state = require_ok(
                client.get("/strategies/bull-put/runtime", params={"external_account_id": "LBPT10087357"})
            )
            assert runtime_state["auto_entry_enabled"] is True
            assert runtime_state["kill_switch_active"] is False
            lottery_runtime = require_ok(
                client.get("/strategies/zero-dte-lottery/runtime", params={"external_account_id": "LBPT10087357"})
            )
            assert lottery_runtime["auto_execute_enabled"] is False
            lottery_preview = require_ok(
                client.get(
                    "/strategies/zero-dte-lottery/preview",
                    params={"external_account_id": "LBPT10087357", "symbol": "QQQ.US", "direction": "auto"},
                )
            )
            assert lottery_preview["eligible"] is True
            initial_executions = require_ok(client.get("/executions", params={"external_account_id": "LBPT10087357"}))
            assert len(initial_executions) == 1
            assert initial_executions[0]["order_id"] == "mock-order-0002"
            initial_journals = require_ok(client.get("/journals", params={"external_account_id": "LBPT10087357"}))
            assert len(initial_journals) == 1
            assert initial_journals[0]["order_id"] == "mock-order-0002"
            broker_profiles = require_ok(client.get("/brokers/profiles"))
            assert broker_profiles[0]["paper_guard"] == "config_declared"
            operator_status = require_ok(
                client.get("/ops/unattended-status", params={"external_account_id": "LBPT10087357", "mode": "paper"})
            )
            assert operator_status["paper_mandate"]["external_account_id"] == "LBPT10087357"
            assert operator_status["audit_summary"]["event_count"] >= 1
            advisor_run_cards = require_ok(
                client.get(
                    "/strategies/advisor/run-cards",
                    params={"external_account_id": "LBPT10087357", "source": "deepseek"},
                )
            )
            assert advisor_run_cards[0]["recorded"] is True
            audit_events = require_ok(client.get("/ops/audit", params={"external_account_id": "LBPT10087357"}))
            assert any(event["action"] == "advisor_run_card_recorded" for event in audit_events)
            audit_summary = require_ok(client.get("/ops/audit/summary", params={"external_account_id": "LBPT10087357", "mode": "paper"}))
            assert audit_summary["event_count"] >= 1
            browser = run_browser_flow(base_url)
            assert browser["operator"]["rendered"] is True
            scenario_evidence = run_scenario_assertions(client, scenario=args.scenario)

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
                            "zero_dte_lottery_seed": True,
                            "spread_seed": True,
                            "execution_seed": True,
                            "journal_seed": True,
                            "operator_posture_seed": True,
                            "advisor_run_card_seed": True,
                            "audit_seed": True,
                            "audit_summary_seed": True,
                            "recover_close_eligibility_seed": True,
                            "browser_flow": True,
                        },
                        "browser": browser,
                        "scenario": args.scenario,
                        "scenario_evidence": scenario_evidence,
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
