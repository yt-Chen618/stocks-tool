from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from regression_common import build_report, emit_report

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ACCOUNT_ID = "LBPT10087357"

SESSION_WORKFLOWS = {
    "morning": ("unattended-status", "consistency-report", "bull-put-real-paper"),
    "midday": ("bull-put-readiness", "zero-dte-lottery-drill", "bull-put-recovery-drill"),
    "evening": ("audit-export", "consistency-report", "unattended-status"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a read-only morning/midday/evening paper operator session gate against a running API."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Local API base URL.")
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID, help="Paper broker account id.")
    parser.add_argument("--session", choices=["morning", "midday", "evening", "full"], default="full")
    parser.add_argument("--symbol", default="QQQ.US", help="Symbol used for readiness checks.")
    parser.add_argument("--timeout-seconds", type=float, default=180.0, help="HTTP timeout for child workflows.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if read-only safety evidence is missing or any broker submit/local repair/destructive action is observed.",
    )
    parser.add_argument(
        "--evidence-dir",
        default=str(ROOT / "artifacts" / "paper-session-gate"),
        help="Directory for child workflow JSON reports.",
    )
    parser.add_argument("--json-output", help="Optional file path for the JSON session report.")
    return parser.parse_args()


def child_command(
    *,
    workflow: str,
    base_url: str,
    account_id: str,
    symbol: str,
    timeout_seconds: float,
    output_path: Path,
) -> list[str]:
    common = [sys.executable, str(ROOT / "scripts" / "run_regression.py"), workflow]
    if workflow == "unattended-status":
        return [
            sys.executable,
            str(ROOT / "scripts" / "run_regression.py"),
            "unattended-paper",
            "status",
            "--base-url",
            base_url,
            "--account-id",
            account_id,
            "--timeout-seconds",
            str(timeout_seconds),
            "--notification-channel",
            "dry-run",
            "--json-output",
            str(output_path),
        ]
    if workflow == "bull-put-real-paper":
        return [
            *common,
            "--base-url",
            base_url,
            "--account-id",
            account_id,
            "--timeout-seconds",
            str(timeout_seconds),
            "--json-output",
            str(output_path),
        ]
    if workflow == "bull-put-readiness":
        return [
            *common,
            "--base-url",
            base_url,
            "--account-id",
            account_id,
            "--symbol",
            symbol,
            "--timeout-seconds",
            str(timeout_seconds),
            "--json-output",
            str(output_path),
        ]
    if workflow == "bull-put-recovery-drill":
        return [
            *common,
            "--base-url",
            base_url,
            "--account-id",
            account_id,
            "--timeout-seconds",
            str(timeout_seconds),
            "--json-output",
            str(output_path),
        ]
    if workflow == "zero-dte-lottery-drill":
        return [
            *common,
            "--base-url",
            base_url,
            "--account-id",
            account_id,
            "--symbol",
            symbol,
            "--timeout-seconds",
            str(timeout_seconds),
            "--json-output",
            str(output_path),
        ]
    if workflow == "audit-export":
        return [
            *common,
            "--base-url",
            base_url,
            "--account-id",
            account_id,
            "--timeout-seconds",
            str(timeout_seconds),
            "--json-output",
            str(output_path),
        ]
    if workflow == "consistency-report":
        return [
            *common,
            "--base-url",
            base_url,
            "--account-id",
            account_id,
            "--timeout-seconds",
            str(timeout_seconds),
            "--json-output",
            str(output_path),
        ]
    raise ValueError(f"Unsupported paper session workflow: {workflow}")


def load_report(path: Path, stdout: str) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(stdout)


def compact_child_report(report: dict[str, Any]) -> dict[str, Any]:
    payload = report.get("payload") if isinstance(report, dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "workflow": report.get("workflow"),
        "status": report.get("status"),
        "summary": report.get("summary"),
        "error": report.get("error"),
        "operator_posture_status": (payload.get("strategy_loop_summary") or {}).get("operator_posture_status")
        if isinstance(payload.get("strategy_loop_summary"), dict)
        else None,
        "event_loop_stall_detected": payload.get("event_loop_stall_detected"),
        "eligible_count": payload.get("eligible_count"),
        "blocked_count": payload.get("blocked_count"),
        "post_endpoint_called": payload.get("post_endpoint_called"),
        "event_count": payload.get("event_count"),
        "preview_eligible": payload.get("preview_eligible"),
        "force_scan_called": payload.get("force_scan_called"),
        "scan_executed": payload.get("scan_executed"),
        "broker_order_submit_allowed": payload.get("broker_order_submit_allowed"),
        "local_repair_available": payload.get("local_repair_available"),
        "local_repair_executed": payload.get("local_repair_executed"),
        "destructive_actions_executed": payload.get("destructive_actions_executed"),
        "consistency_status": ((payload.get("consistency") or {}).get("status"))
        if isinstance(payload.get("consistency"), dict)
        else None,
        "consistency_check_count": ((payload.get("consistency") or {}).get("check_count"))
        if isinstance(payload.get("consistency"), dict)
        else None,
    }


def run_child(command: list[str], output_path: Path, timeout_seconds: float) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )
    duration_seconds = round(time.monotonic() - started, 3)
    child = {
        "command": command,
        "returncode": completed.returncode,
        "report_path": str(output_path),
        "duration_seconds": duration_seconds,
    }
    try:
        report = load_report(output_path, completed.stdout)
        child.update(compact_child_report(report))
    except Exception as error:
        child["parse_error"] = str(error)
        child["stdout_tail"] = completed.stdout[-500:]
        child["stderr_tail"] = completed.stderr[-500:]
    if completed.returncode != 0:
        child["status"] = "failed"
        child["error"] = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
    return child


def workflows_for_session(session: str) -> list[tuple[str, str]]:
    sessions = ("morning", "midday", "evening") if session == "full" else (session,)
    return [
        (session_name, workflow)
        for session_name in sessions
        for workflow in SESSION_WORKFLOWS[session_name]
    ]


def strict_violations(children: list[dict[str, Any]]) -> list[str]:
    violations: list[str] = []
    if not any(child.get("name") == "consistency-report" for child in children):
        violations.append("missing consistency-report child workflow")
    for child in children:
        name = child.get("name")
        if child.get("broker_order_submit_allowed") is True:
            violations.append(f"{name} reported broker_order_submit_allowed=true")
        if child.get("local_repair_executed") is True:
            violations.append(f"{name} reported local_repair_executed=true")
        if child.get("destructive_actions_executed") is True:
            violations.append(f"{name} reported destructive_actions_executed=true")
    return violations


def main() -> None:
    args = parse_args()
    evidence_dir = Path(args.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    children: list[dict[str, Any]] = []
    failed = False
    for session_name, workflow in workflows_for_session(args.session):
        output_path = evidence_dir / f"{session_name}-{workflow}.json"
        command = child_command(
            workflow=workflow,
            base_url=args.base_url.rstrip("/"),
            account_id=args.account_id,
            symbol=args.symbol,
            timeout_seconds=args.timeout_seconds,
            output_path=output_path,
        )
        child = run_child(command, output_path, timeout_seconds=args.timeout_seconds + 30)
        child["session"] = session_name
        child["name"] = workflow
        children.append(child)
        failed = failed or child.get("status") == "failed" or child.get("returncode") != 0

    strict_failure_reasons = strict_violations(children) if args.strict else []
    failed = failed or bool(strict_failure_reasons)
    status = "failed" if failed else "passed"
    broker_order_submit_allowed = any(child.get("broker_order_submit_allowed") is True for child in children)
    local_repair_available = any(child.get("local_repair_available") is True for child in children)
    local_repair_executed = any(child.get("local_repair_executed") is True for child in children)
    destructive_actions_executed = any(child.get("destructive_actions_executed") is True for child in children)
    child_status_counts: dict[str, int] = {}
    for child in children:
        child_status = str(child.get("status") or "unknown")
        child_status_counts[child_status] = child_status_counts.get(child_status, 0) + 1
    emit_report(
        build_report(
            script="run_paper_session_gate.py",
            workflow="paper-session-gate",
            status=status,
            mode="paper",
            target=args.base_url.rstrip("/"),
            summary=(
                f"Paper session gate {args.session} {'failed' if failed else 'passed'} "
                f"with {len(children)} child workflow(s)."
            ),
            payload={
                "manifest_schema_version": "paper_session_gate_v2",
                "account_id": args.account_id,
                "session": args.session,
                "strict": args.strict,
                "symbol": args.symbol,
                "children": children,
                "child_artifact_paths": [child.get("report_path") for child in children if child.get("report_path")],
                "child_status_counts": child_status_counts,
                "strict_failure_reasons": strict_failure_reasons,
                "destructive_actions_executed": destructive_actions_executed,
                "broker_order_submit_allowed": broker_order_submit_allowed,
                "local_repair_available": local_repair_available,
                "local_repair_executed": local_repair_executed,
            },
        ),
        json_output=args.json_output,
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
