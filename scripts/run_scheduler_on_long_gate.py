from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from regression_common import build_report, emit_report

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST = "127.0.0.1"
DEFAULT_ACCOUNT_ID = "LBPT10087357"


class SchedulerGateError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Start a temporary scheduler-enabled API and run the long paper operator gate: "
            "real-ui-refresh, unattended-paper status, and bull-put-real-paper."
        )
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Temporary API bind host.")
    parser.add_argument("--port", type=int, default=8000, help="Preferred temporary API port.")
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID, help="Paper broker account id.")
    parser.add_argument("--iterations", type=int, default=2, help="real-ui-refresh iterations.")
    parser.add_argument("--boot-timeout-seconds", type=float, default=60.0, help="API boot timeout.")
    parser.add_argument("--child-timeout-seconds", type=float, default=240.0, help="Timeout for each child gate.")
    parser.add_argument("--http-timeout-seconds", type=float, default=120.0, help="HTTP timeout passed to child gates.")
    parser.add_argument(
        "--evidence-dir",
        default=str(ROOT / "artifacts" / "scheduler-on-long-gate"),
        help="Directory for child JSON reports and API logs.",
    )
    parser.add_argument("--json-output", help="Optional file path for the JSON regression report.")
    return parser.parse_args()


def choose_port(host: str, preferred_port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, preferred_port))
            return preferred_port
        except OSError:
            sock.bind((host, 0))
            return int(sock.getsockname()[1])


def wait_for_api(base_url: str, *, timeout_seconds: float, process: subprocess.Popen[str]) -> float:
    deadline = time.monotonic() + timeout_seconds
    started = time.monotonic()
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SchedulerGateError(f"Temporary API exited early with code {process.returncode}.")
        try:
            response = httpx.get(f"{base_url}/health", timeout=2.0)
            if response.is_success:
                return (time.monotonic() - started) * 1000
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SchedulerGateError(f"Temporary API did not become healthy within {timeout_seconds} seconds.")


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def load_report(path: Path, stdout: str) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(stdout)


def compact_report_payload(report: dict[str, Any]) -> dict[str, Any]:
    payload = report.get("payload")
    if not isinstance(payload, dict):
        return {}
    workflow = report.get("workflow")
    if workflow == "real-local-dashboard-refresh-regression":
        runs = payload.get("runs")
        return {
            "summary": payload.get("summary"),
            "run_count": len(runs) if isinstance(runs, list) else 0,
        }
    if workflow == "unattended-paper-status":
        audit_summary = payload.get("audit_summary")
        groups = audit_summary.get("groups") if isinstance(audit_summary, dict) else []
        operator_status = payload.get("operator_status")
        checks = operator_status.get("checks") if isinstance(operator_status, dict) else []
        return {
            "strategy_loop_summary": payload.get("strategy_loop_summary"),
            "operator_posture_reason": payload.get("operator_posture_reason"),
            "operator_reason_codes": payload.get("operator_reason_codes"),
            "operator_check_count": len(checks) if isinstance(checks, list) else 0,
            "audit_summary_group_count": len(groups) if isinstance(groups, list) else 0,
        }
    if workflow == "bull-put-real-paper-smoke":
        eligible_symbols = payload.get("eligible_symbols")
        previews = payload.get("previews")
        return {
            "eligible_symbol_count": len(eligible_symbols) if isinstance(eligible_symbols, list) else 0,
            "preview_count": len(previews) if isinstance(previews, list) else 0,
        }
    if workflow == "bull-put-recovery-drill":
        return {
            "inspected_spread_count": payload.get("inspected_spread_count"),
            "eligible_count": payload.get("eligible_count"),
            "blocked_count": payload.get("blocked_count"),
            "post_endpoint_called": payload.get("post_endpoint_called"),
        }
    return {"payload_keys": sorted(payload.keys())}


def tail_text(value: str, limit: int = 500) -> str:
    return value[-limit:] if len(value) > limit else value


def run_child_gate(
    *,
    name: str,
    command: list[str],
    output_path: Path,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
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
    child = {
        "name": name,
        "command": command,
        "returncode": completed.returncode,
        "stdout_tail": tail_text(completed.stdout.strip()),
        "stderr_tail": tail_text(completed.stderr.strip()),
    }
    report: dict[str, Any] = {}
    try:
        report = load_report(output_path, completed.stdout)
        child.update(
            {
                "report_path": str(output_path),
                "report_status": report.get("status"),
                "report_summary": report.get("summary"),
                "report_error": report.get("error"),
                "report_payload": compact_report_payload(report),
            }
        )
    except Exception as error:
        child["parse_error"] = str(error)
    if completed.returncode != 0:
        raise SchedulerGateError(
            f"{name} failed with code {completed.returncode}: "
            f"{completed.stderr.strip() or completed.stdout.strip() or 'no output'}"
        )
    return child, report


def scheduler_backoff_reason(unattended_report: dict[str, Any]) -> str | None:
    payload = unattended_report.get("payload") if isinstance(unattended_report, dict) else {}
    operator_status = payload.get("operator_status") if isinstance(payload, dict) else {}
    checks = operator_status.get("checks") if isinstance(operator_status, dict) else []
    for check in checks:
        if isinstance(check, dict) and check.get("reason_code") == "scheduler_backoff":
            return check.get("detail")
    return None


def scheduler_summaries(unattended_report: dict[str, Any]) -> list[dict[str, Any]]:
    payload = unattended_report.get("payload") if isinstance(unattended_report.get("payload"), dict) else {}
    operator_status = payload.get("operator_status") if isinstance(payload, dict) else {}
    summaries = operator_status.get("recent_scheduler_summaries") if isinstance(operator_status, dict) else None
    if isinstance(summaries, list):
        return [summary for summary in summaries if isinstance(summary, dict)]
    loop_summary = payload.get("strategy_loop_summary") if isinstance(payload, dict) else {}
    summaries = loop_summary.get("recent_scheduler_summaries") if isinstance(loop_summary, dict) else None
    if isinstance(summaries, list):
        return [summary for summary in summaries if isinstance(summary, dict)]
    return []


def scheduler_lease_evidence(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "job_key": summary.get("job_key"),
            "external_account_id": summary.get("external_account_id"),
            "lease_status": summary.get("lease_status"),
            "lease_expires_at": summary.get("lease_expires_at"),
            "next_attempt_source": summary.get("next_attempt_source"),
            "due_status": summary.get("due_status"),
        }
        for summary in summaries
        if summary.get("lease_status") or summary.get("next_attempt_source") in {"lease", "backoff"}
    ]


def main() -> None:
    args = parse_args()
    evidence_dir = Path(args.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    port = choose_port(args.host, args.port)
    base_url = f"http://{args.host}:{port}"
    log_path = evidence_dir / "api.log"
    log_handle = log_path.open("w", encoding="utf-8")
    env = {
        **os.environ,
        "RECONCILIATION_SCHEDULER_ENABLED": "true",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "--app-dir",
            "src",
            "stocks_tool.main:app",
            "--host",
            args.host,
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    child_reports: list[dict[str, Any]] = []
    try:
        boot_time_ms = wait_for_api(base_url, timeout_seconds=args.boot_timeout_seconds, process=process)
        real_ui_path = evidence_dir / "real-ui-refresh.json"
        unattended_path = evidence_dir / "unattended-paper-status.json"
        bull_put_path = evidence_dir / "bull-put-real-paper.json"
        recovery_drill_path = evidence_dir / "bull-put-recovery-drill.json"
        real_ui_child, real_ui_report = run_child_gate(
            name="real-ui-refresh",
            command=[
                sys.executable,
                str(ROOT / "scripts" / "run_real_local_dashboard_refresh_regression.py"),
                "--base-url",
                base_url,
                "--iterations",
                str(args.iterations),
                "--json-output",
                str(real_ui_path),
            ],
            output_path=real_ui_path,
            timeout_seconds=args.child_timeout_seconds,
        )
        child_reports.append(real_ui_child)
        unattended_child, unattended_report = run_child_gate(
            name="unattended-paper-status",
            command=[
                sys.executable,
                str(ROOT / "scripts" / "run_unattended_paper.py"),
                "status",
                "--base-url",
                base_url,
                "--account-id",
                args.account_id,
                "--timeout-seconds",
                str(args.http_timeout_seconds),
                "--notification-channel",
                "dry-run",
                "--json-output",
                str(unattended_path),
            ],
            output_path=unattended_path,
            timeout_seconds=args.child_timeout_seconds,
        )
        child_reports.append(unattended_child)
        bull_put_child, _bull_put_report = run_child_gate(
            name="bull-put-real-paper",
            command=[
                sys.executable,
                str(ROOT / "scripts" / "run_bull_put_real_paper_smoke.py"),
                "--base-url",
                base_url,
                "--account-id",
                args.account_id,
                "--timeout-seconds",
                str(args.http_timeout_seconds),
                "--json-output",
                str(bull_put_path),
            ],
            output_path=bull_put_path,
            timeout_seconds=args.child_timeout_seconds,
        )
        child_reports.append(bull_put_child)
        recovery_drill_child, _recovery_drill_report = run_child_gate(
            name="bull-put-recovery-drill",
            command=[
                sys.executable,
                str(ROOT / "scripts" / "run_bull_put_recovery_drill.py"),
                "--base-url",
                base_url,
                "--account-id",
                args.account_id,
                "--timeout-seconds",
                str(args.http_timeout_seconds),
                "--json-output",
                str(recovery_drill_path),
            ],
            output_path=recovery_drill_path,
            timeout_seconds=args.child_timeout_seconds,
        )
        child_reports.append(recovery_drill_child)
        real_ui_summary = ((real_ui_report.get("payload") or {}).get("summary") or {})
        dashboard_ready = real_ui_summary.get("dashboard_ready") or {}
        overlay_settled = real_ui_summary.get("overlay_settled") or {}
        unattended_summary = ((unattended_report.get("payload") or {}).get("strategy_loop_summary") or {})
        scheduler_summary_payload = scheduler_summaries(unattended_report)
        event_loop_stall_detected = bool(
            dashboard_ready.get("within_target") is False
            or overlay_settled.get("within_target") is False
        )
        emit_report(
            build_report(
                script="run_scheduler_on_long_gate.py",
                workflow="scheduler-on-long-gate",
                status="passed",
                mode="paper",
                target=base_url,
                summary=(
                    "Scheduler-enabled long gate passed. "
                    f"API boot {int(boot_time_ms)}ms; dashboard max "
                    f"{dashboard_ready.get('max_ms')}ms."
                ),
                payload={
                    "account_id": args.account_id,
                    "api_boot_time_ms": int(boot_time_ms),
                    "api_log_path": str(log_path),
                    "scheduler_enabled_env": True,
                    "event_loop_stall_detected": event_loop_stall_detected,
                    "dashboard_ready": dashboard_ready,
                    "overlay_settled": overlay_settled,
                    "operator_posture_status": unattended_summary.get("operator_posture_status"),
                    "operator_posture_reason": unattended_summary.get("operator_posture_reason"),
                    "scheduler_backoff_reason": scheduler_backoff_reason(unattended_report),
                    "scheduler_summaries": scheduler_summary_payload,
                    "scheduler_lease_evidence": scheduler_lease_evidence(scheduler_summary_payload),
                    "child_gates": child_reports,
                },
            ),
            json_output=args.json_output,
        )
    except Exception as error:
        emit_report(
            build_report(
                script="run_scheduler_on_long_gate.py",
                workflow="scheduler-on-long-gate",
                status="failed",
                mode="paper",
                target=base_url,
                summary="Scheduler-enabled long gate failed.",
                error=str(error),
                payload={
                    "account_id": args.account_id,
                    "api_log_path": str(log_path),
                    "child_gates": child_reports,
                },
            ),
            json_output=args.json_output,
        )
        raise SystemExit(1)
    finally:
        stop_process(process)
        log_handle.close()


if __name__ == "__main__":
    main()
