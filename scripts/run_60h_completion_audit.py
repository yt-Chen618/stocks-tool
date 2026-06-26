from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from regression_common import build_report, emit_report

ROOT = Path(__file__).resolve().parents[1]

EvidenceCheck = Callable[[Path], tuple[str, str, dict[str, Any]]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit current evidence against the 60h operator hardening plan without redefining completion."
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(ROOT / "artifacts"),
        help="Directory containing JSON evidence from regression scripts.",
    )
    parser.add_argument("--json-output", help="Optional file path for the JSON audit report.")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def latest_report(artifacts_dir: Path, pattern: str) -> dict[str, Any] | None:
    matches = sorted(artifacts_dir.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in matches:
        report = load_json(path)
        if report is not None:
            report["_path"] = str(path)
            return report
    return None


def check_worktree_inventory(artifacts_dir: Path) -> tuple[str, str, dict[str, Any]]:
    report = latest_report(artifacts_dir, "worktree-release-inventory*.json")
    if report is None:
        return "missing", "No worktree-release-inventory evidence found.", {}
    payload = report.get("payload") or {}
    unknown = payload.get("unknown_paths") or []
    generated = payload.get("generated_candidates") or []
    if report.get("status") == "passed" and not unknown and not generated:
        return "proved", "Dirty worktree is classified into review slices with no unknown/generated candidates.", payload
    return "incomplete", "Worktree inventory is not clean enough for release slicing.", payload


def check_scheduler_long_gate(artifacts_dir: Path) -> tuple[str, str, dict[str, Any]]:
    report = latest_report(artifacts_dir, "scheduler-on-long-gate*.json")
    if report is None:
        return "missing", "No scheduler-on-long-gate evidence found.", {}
    payload = report.get("payload") or {}
    if report.get("status") == "passed" and payload.get("event_loop_stall_detected") is False:
        return "proved", "Scheduler-enabled gate passed without an event-loop stall.", payload
    return "incomplete", "Scheduler-enabled gate did not prove nonblocking behavior.", payload


def check_paper_session_gate(artifacts_dir: Path) -> tuple[str, str, dict[str, Any]]:
    report = latest_report(artifacts_dir, "paper-session-gate*.json")
    if report is None:
        return "missing", "No paper-session-gate evidence found.", {}
    payload = report.get("payload") or {}
    children = payload.get("children") or []
    names = {child.get("name") for child in children if isinstance(child, dict)}
    required = {
        "unattended-status",
        "bull-put-real-paper",
        "bull-put-readiness",
        "zero-dte-lottery-drill",
        "bull-put-recovery-drill",
        "audit-export",
        "consistency-report",
    }
    missing_names = sorted(required - names)
    if (
        report.get("status") == "passed"
        and not missing_names
        and payload.get("destructive_actions_executed") is False
        and payload.get("broker_order_submit_allowed") is False
        and payload.get("local_repair_executed") is not True
    ):
        return "proved", "Full paper-session gate passed with read-only broker posture.", payload
    return "incomplete", f"Paper-session gate missing or unsafe child evidence: {missing_names}.", payload


def check_zero_dte_drill(artifacts_dir: Path) -> tuple[str, str, dict[str, Any]]:
    report = latest_report(artifacts_dir, "zero-dte-lottery-drill*.json")
    if report is None:
        return "missing", "No zero-dte-lottery-drill evidence found.", {}
    payload = report.get("payload") or {}
    confirmed_force_scan = payload.get("force_scan_called") is True or payload.get("force_scan_evidence_reconciled") is True
    strategy_recording_verified = payload.get("strategy_recording_verified") is True
    if (
        report.get("status") == "passed"
        and confirmed_force_scan
        and payload.get("confirm_paper_scan") is True
        and strategy_recording_verified
    ):
        return "proved", "Confirmed force-scan evidence and strategy recording exist.", payload
    if payload.get("force_scan_requested") is True and payload.get("confirm_paper_scan") is True:
        return (
            "incomplete",
            "Confirmed force-scan was attempted but did not produce passing order and strategy-recording evidence.",
            payload,
        )
    if payload.get("broker_order_submit_allowed") is False:
        return "manual_required", "Preview-only zero-DTE evidence exists; confirmed force-scan evidence is still absent.", payload
    return "incomplete", "Zero-DTE drill evidence is not in a safe or confirmed state.", payload


def check_data_hygiene(artifacts_dir: Path) -> tuple[str, str, dict[str, Any]]:
    report = latest_report(artifacts_dir, "data-hygiene-audit*.json")
    if report is None:
        return "missing", "No data-hygiene-audit evidence found.", {}
    payload = report.get("payload") or {}
    plan = payload.get("cleanup_plan") or {}
    if payload.get("destructive_actions_executed") is False and plan.get("safe_by_default") is True:
        return "proved", "Data hygiene evidence is read-only and includes a manual cleanup plan.", payload
    return "incomplete", "Data hygiene evidence does not prove safe-by-default cleanup planning.", payload


def check_advisor_intake(artifacts_dir: Path) -> tuple[str, str, dict[str, Any]]:
    report = latest_report(artifacts_dir, "advisor-intake*.json")
    if report is None:
        return "missing", "No advisor-intake evidence found.", {}
    payload = report.get("payload") or {}
    context = payload.get("context") if isinstance(payload, dict) else {}
    hard_rules = context.get("hard_rules") if isinstance(context, dict) else []
    rule_names = {rule.get("name") for rule in hard_rules if isinstance(rule, dict)}
    if report.get("status") == "passed" and payload.get("recorded") is False and "advisor_context_is_read_only" in rule_names:
        return "proved", "Advisor intake evidence is read-only and was not recorded by default.", payload
    return "incomplete", "Advisor intake evidence does not prove read-only default behavior.", payload


def check_mock_ui_matrix(artifacts_dir: Path) -> tuple[str, str, dict[str, Any]]:
    report = latest_report(artifacts_dir, "mock-ui*.json") or latest_report(artifacts_dir, "mock-dashboard*.json")
    if report is None:
        return "missing", "No mock UI scenario evidence found.", {}
    payload = report.get("payload") or {}
    scenarios = payload.get("scenarios") or []
    if report.get("status") == "passed" and len(scenarios) >= 9:
        return "proved", "Mock UI scenario matrix evidence covers posture and recovery scenarios.", payload
    return "incomplete", "Mock UI matrix evidence is missing scenario coverage.", payload


def check_multi_session_evidence(artifacts_dir: Path) -> tuple[str, str, dict[str, Any]]:
    reports = [
        report
        for path in artifacts_dir.glob("paper-session-gate*.json")
        if (report := load_json(path)) is not None and report.get("status") == "passed"
    ]
    generated = sorted({str(report.get("generated_at")) for report in reports if report.get("generated_at")})
    payload = {"passed_report_count": len(reports), "generated_at_values": generated}
    if len(generated) >= 2:
        return "proved", "At least two paper-session gate evidence files exist.", payload
    return "manual_required", "Repeated paper-session evidence across separate operator sessions is still thin.", payload


REQUIREMENTS: tuple[tuple[str, str, EvidenceCheck], ...] = (
    ("phase_1_worktree_freeze", "Worktree freeze and release-slice prep", check_worktree_inventory),
    ("phase_2_scheduler_nonblocking", "Scheduler-on Longbridge gate and nonblocking posture", check_scheduler_long_gate),
    ("phase_3_operator_session_loop", "Morning/midday/evening paper session evidence loop", check_paper_session_gate),
    ("phase_4_zero_dte_validation", "Zero-DTE preview plus confirmed force-scan validation", check_zero_dte_drill),
    ("phase_5_data_hygiene", "Read-only data hygiene and cleanup plan", check_data_hygiene),
    ("phase_6_advisor_guardrail", "Advisor default read-only guardrail evidence", check_advisor_intake),
    ("phase_7_mock_scenarios", "Mock scenario matrix evidence", check_mock_ui_matrix),
    ("phase_8_repeated_sessions", "Repeated real paper-session evidence", check_multi_session_evidence),
)


def main() -> None:
    args = parse_args()
    artifacts_dir = Path(args.artifacts_dir)
    requirements: list[dict[str, Any]] = []
    for requirement_id, title, check in REQUIREMENTS:
        status, summary, evidence = check(artifacts_dir)
        requirements.append(
            {
                "id": requirement_id,
                "title": title,
                "status": status,
                "summary": summary,
                "evidence": evidence,
            }
        )
    counts: dict[str, int] = {}
    for item in requirements:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    complete = counts.get("missing", 0) == 0 and counts.get("incomplete", 0) == 0 and counts.get("manual_required", 0) == 0
    status = "passed" if complete else "incomplete"
    emit_report(
        build_report(
            script="run_60h_completion_audit.py",
            workflow="60h-completion-audit",
            status=status,
            mode="local",
            target=str(artifacts_dir),
            summary=(
                "60h completion audit "
                + ("proved complete." if complete else f"is not complete: {counts}.")
            ),
            payload={
                "goal_complete": complete,
                "status_counts": counts,
                "requirements": requirements,
            },
        ),
        json_output=args.json_output,
    )
    if not complete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
