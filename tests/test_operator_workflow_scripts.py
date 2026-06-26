from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.append(str(SCRIPTS_DIR))

from run_60h_completion_audit import check_data_hygiene, check_paper_session_gate, check_zero_dte_drill  # noqa: E402
from run_data_hygiene_audit import (  # noqa: E402
    archive_stale_generated_files,
    cleanup_plan,
    cleanup_project_caches,
    retention_report,
    watchlist_audit,
)
from run_paper_session_gate import child_command, compact_child_report, strict_violations, workflows_for_session  # noqa: E402
from run_scheduler_on_long_gate import scheduler_lease_evidence, scheduler_summaries  # noqa: E402
from run_worktree_release_inventory import classify_path, is_generated_path  # noqa: E402
from run_zero_dte_lottery_drill import (  # noqa: E402
    ZeroDteHttpError,
    force_scan_order_brief,
    is_preview_degraded_warning,
    summarize_drill,
)


def test_worktree_release_inventory_classifies_known_slices() -> None:
    assert classify_path("alembic/versions/20260618_0015_scheduler_task_states.py") == (
        "operator_status_audit_scheduler"
    )
    assert classify_path("src/stocks_tool/application/services/operator_status.py") == (
        "operator_status_audit_scheduler"
    )
    assert classify_path("src/stocks_tool/application/services/operator_consistency.py") == (
        "operator_status_audit_scheduler"
    )
    assert classify_path("src/stocks_tool/ui/static/app.js") == "dashboard_mock_regression"
    assert classify_path(".playwright-cli/page.yml") == "generated_cleanup"
    assert classify_path(".vscode/PythonImportHelper-v2-Completion.json") == "generated_cleanup"
    assert classify_path(".gitignore") == "generated_cleanup"
    assert classify_path("debug.log") == "generated_cleanup"
    assert classify_path("docs/operator-platform-v4-runbook.md") == "docs_tests"
    assert classify_path("random.tmp") == "unknown"


def test_worktree_release_inventory_flags_generated_artifacts() -> None:
    assert is_generated_path("artifacts/scheduler-on-long-gate.json")
    assert is_generated_path("output/playwright/dashboard.png")
    assert is_generated_path("src/stocks_tool/__pycache__/main.cpython-312.pyc")
    assert is_generated_path("tests/.pytest_cache/v/cache/nodeids")
    assert not is_generated_path("scripts/run_regression.py")


def test_data_hygiene_audit_identifies_duplicate_and_test_watchlists() -> None:
    report = watchlist_audit(
        [
            {"id": "1", "name": "core-us", "symbols": ["QQQ.US"]},
            {"id": "2", "name": "Core-US", "symbols": ["SPY.US"]},
            {"id": "3", "name": "string", "symbols": []},
        ]
    )

    assert report["duplicate_names"] == ["core-us"]
    assert report["test_residue_names"] == ["string"]
    assert report["count"] == 3


def test_data_hygiene_cleanup_plan_is_manual_and_preserves_ledgers() -> None:
    plan = cleanup_plan(
        watchlists={
            "duplicate_names": ["core-us"],
            "test_residue_names": ["string"],
        },
        artifacts={"file_count": 2, "total_bytes": 128},
        playwright={"file_count": 1, "total_bytes": 64},
    )

    assert plan["safe_by_default"] is True
    assert plan["destructive_actions_executed"] is False
    assert all(action["requires_manual_confirmation"] is True for action in plan["actions"])
    assert "orders" in plan["never_delete_without_backup"]
    assert "strategy_audit_events" in plan["never_delete_without_backup"]
    assert "scheduler_task_states" in plan["never_delete_without_backup"]


def test_data_hygiene_retention_report_finds_stale_notifications_and_screenshots(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    screenshots = tmp_path / "output" / "playwright"
    artifacts.mkdir(parents=True)
    screenshots.mkdir(parents=True)
    notification = artifacts / "unattended-paper-notifications.jsonl"
    screenshot = screenshots / "dashboard.png"
    notification.write_text('{"old": true}\n', encoding="utf-8")
    screenshot.write_bytes(b"png")
    old_timestamp = datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()
    notification.touch()
    screenshot.touch()
    import os

    os.utime(notification, (old_timestamp, old_timestamp))
    os.utime(screenshot, (old_timestamp, old_timestamp))

    report = retention_report(
        tmp_path,
        retention_days=7,
        now=datetime(2026, 6, 18, tzinfo=timezone.utc),
    )
    plan = cleanup_plan(
        watchlists={"duplicate_names": [], "test_residue_names": []},
        artifacts={"file_count": 0, "total_bytes": 0},
        playwright={"file_count": 0, "total_bytes": 0},
        retention=report,
    )

    assert report["candidate_count"] >= 2
    assert report["categories"]["stale_jsonl_notifications"]["candidate_count"] == 1
    assert report["categories"]["old_playwright_screenshots"]["candidate_count"] == 1
    assert any(action["action"] == "review_retention_candidates" for action in plan["actions"])
    assert plan["destructive_actions_executed"] is False


def test_data_hygiene_archive_stale_generated_files_moves_candidates(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    screenshots = tmp_path / "output" / "playwright"
    archive_root = tmp_path / "archives"
    artifacts.mkdir(parents=True)
    screenshots.mkdir(parents=True)
    old_artifact = artifacts / "old.json"
    old_screenshot = screenshots / "old.png"
    fresh_artifact = artifacts / "fresh.json"
    old_artifact.write_text("{}", encoding="utf-8")
    old_screenshot.write_bytes(b"png")
    fresh_artifact.write_text("{}", encoding="utf-8")
    old_now = datetime(2026, 6, 18, tzinfo=timezone.utc)
    old_timestamp = datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()
    import os

    os.utime(old_artifact, (old_timestamp, old_timestamp))
    os.utime(old_screenshot, (old_timestamp, old_timestamp))

    result = archive_stale_generated_files(
        tmp_path,
        retention_days=7,
        archive_root=archive_root,
        now=old_now,
    )

    assert result["moved_count"] == 2
    assert not old_artifact.exists()
    assert not old_screenshot.exists()
    assert fresh_artifact.exists()
    assert Path(result["archive"], "cleanup-manifest.json").exists()


def test_data_hygiene_cleanup_project_caches_removes_project_cache_only(tmp_path: Path) -> None:
    project_cache = tmp_path / "src" / "__pycache__"
    pytest_cache = tmp_path / ".pytest_cache"
    venv_cache = tmp_path / ".venv" / "Lib" / "site-packages" / "__pycache__"
    project_cache.mkdir(parents=True)
    pytest_cache.mkdir()
    venv_cache.mkdir(parents=True)
    (project_cache / "module.pyc").write_bytes(b"cache")
    (pytest_cache / "nodeids").write_text("[]", encoding="utf-8")
    (venv_cache / "dependency.pyc").write_bytes(b"cache")

    result = cleanup_project_caches(tmp_path)

    assert result["removed_count"] == 2
    assert not project_cache.exists()
    assert not pytest_cache.exists()
    assert venv_cache.exists()


def test_paper_session_gate_expands_full_session_order() -> None:
    assert workflows_for_session("full") == [
        ("morning", "unattended-status"),
        ("morning", "consistency-report"),
        ("morning", "bull-put-real-paper"),
        ("midday", "bull-put-readiness"),
        ("midday", "zero-dte-lottery-drill"),
        ("midday", "bull-put-recovery-drill"),
        ("evening", "audit-export"),
        ("evening", "consistency-report"),
        ("evening", "unattended-status"),
    ]


def test_paper_session_gate_recovery_drill_child_is_read_only(tmp_path: Path) -> None:
    command = child_command(
        workflow="bull-put-recovery-drill",
        base_url="http://127.0.0.1:8000",
        account_id="LBPT10087357",
        symbol="QQQ.US",
        timeout_seconds=30,
        output_path=tmp_path / "recovery.json",
    )

    assert "bull-put-recovery-drill" in command
    assert "recover-close" not in " ".join(command)


def test_paper_session_gate_zero_dte_child_is_preview_only(tmp_path: Path) -> None:
    command = child_command(
        workflow="zero-dte-lottery-drill",
        base_url="http://127.0.0.1:8000",
        account_id="LBPT10087357",
        symbol="QQQ.US",
        timeout_seconds=30,
        output_path=tmp_path / "zero-dte.json",
    )

    rendered = " ".join(command)
    assert "zero-dte-lottery-drill" in command
    assert "--force-scan" not in rendered
    assert "--confirm-paper-scan" not in rendered


def test_paper_session_gate_consistency_child_is_read_only(tmp_path: Path) -> None:
    command = child_command(
        workflow="consistency-report",
        base_url="http://127.0.0.1:8000",
        account_id="LBPT10087357",
        symbol="QQQ.US",
        timeout_seconds=30,
        output_path=tmp_path / "consistency.json",
    )

    rendered = " ".join(command)
    assert "consistency-report" in command
    assert "repairs" not in rendered


def test_paper_session_gate_strict_detects_missing_consistency_and_effectful_actions() -> None:
    violations = strict_violations(
        [
            {"name": "unattended-status", "broker_order_submit_allowed": False},
            {"name": "zero-dte-lottery-drill", "broker_order_submit_allowed": True},
            {"name": "local-repair", "local_repair_executed": True},
        ]
    )

    assert "missing consistency-report child workflow" in violations
    assert "zero-dte-lottery-drill reported broker_order_submit_allowed=true" in violations
    assert "local-repair reported local_repair_executed=true" in violations


def test_paper_session_gate_compact_child_preserves_repair_evidence() -> None:
    compact = compact_child_report(
        {
            "workflow": "consistency-report",
            "status": "warning",
            "summary": "Consistency warning.",
            "payload": {
                "local_repair_available": True,
                "local_repair_executed": False,
                "destructive_actions_executed": False,
                "consistency": {"status": "warn", "check_count": 3},
            },
        }
    )

    assert compact["local_repair_available"] is True
    assert compact["local_repair_executed"] is False
    assert compact["destructive_actions_executed"] is False
    assert compact["consistency_status"] == "warn"


def test_scheduler_on_gate_extracts_lease_evidence_from_unattended_report() -> None:
    report = {
        "payload": {
            "operator_status": {
                "recent_scheduler_summaries": [
                    {
                        "job_key": "orders-sync",
                        "external_account_id": "LBPT10087357",
                        "due_status": "lease_active",
                        "lease_status": "active",
                        "lease_expires_at": "2026-06-18T14:35:00Z",
                        "next_attempt_source": "lease",
                    }
                ]
            }
        }
    }

    summaries = scheduler_summaries(report)
    evidence = scheduler_lease_evidence(summaries)

    assert evidence == [
        {
            "job_key": "orders-sync",
            "external_account_id": "LBPT10087357",
            "lease_status": "active",
            "lease_expires_at": "2026-06-18T14:35:00Z",
            "next_attempt_source": "lease",
            "due_status": "lease_active",
        }
    ]


def test_zero_dte_lottery_drill_summary_marks_preview_only() -> None:
    summary = summarize_drill(
        runtime={"auto_execute_enabled": False},
        preview={"eligible": True},
        force_scan_called=False,
        scan=None,
    )

    assert "preview=eligible" in summary
    assert "auto_execute=off" in summary
    assert "force_scan_called=false" in summary
    assert "scan=not-called" in summary


def test_zero_dte_lottery_drill_degrades_preview_broker_errors_to_warning() -> None:
    assert is_preview_degraded_warning(ZeroDteHttpError("broker unavailable", status_code=502))
    assert is_preview_degraded_warning(ZeroDteHttpError("broker unavailable", status_code=503))
    assert not is_preview_degraded_warning(ZeroDteHttpError("bad request", status_code=400))


def test_zero_dte_lottery_drill_identifies_manual_force_scan_order() -> None:
    brief = force_scan_order_brief(
        {
            "id": "order-1",
            "external_order_id": "external-1",
            "symbol": "QQQ260616P731000.US",
            "status": "filled",
            "mode": "paper",
            "side": "buy",
            "asset_type": "option",
            "quantity": "1",
            "limit_price": "0.74",
            "submitted_at": "2026-06-16T15:59:32+00:00",
            "raw_payload": {
                "submission_request": {
                    "remark": "zero_dte_lottery_v1:manual-scan",
                    "option_contract": {"underlying_symbol": "QQQ.US"},
                }
            },
        },
        symbol="QQQ.US",
        premium_cap="150",
    )

    assert brief is not None
    assert brief["id"] == "order-1"
    assert brief["premium_at_limit"] == "74.00"


def test_zero_dte_lottery_drill_rejects_manual_force_scan_order_over_cap() -> None:
    brief = force_scan_order_brief(
        {
            "status": "filled",
            "mode": "paper",
            "side": "buy",
            "asset_type": "option",
            "quantity": "1",
            "limit_price": "1.51",
            "raw_payload": {
                "submission_request": {
                    "remark": "zero_dte_lottery_v1:manual-scan",
                    "option_contract": {"underlying_symbol": "QQQ.US"},
                }
            },
        },
        symbol="QQQ.US",
        premium_cap="150",
    )

    assert brief is None


def test_60h_audit_treats_preview_only_zero_dte_as_manual_required(tmp_path: Path) -> None:
    (tmp_path / "zero-dte-lottery-drill.json").write_text(
        """
{
  "status": "warning",
  "payload": {
    "force_scan_called": false,
    "confirm_paper_scan": false,
    "broker_order_submit_allowed": false
  }
}
""".strip(),
        encoding="utf-8",
    )

    status, summary, _evidence = check_zero_dte_drill(tmp_path)

    assert status == "manual_required"
    assert "confirmed force-scan evidence is still absent" in summary


def test_60h_audit_rejects_failed_confirmed_zero_dte_scan(tmp_path: Path) -> None:
    (tmp_path / "zero-dte-lottery-drill.json").write_text(
        """
{
  "status": "failed",
  "payload": {
    "force_scan_requested": true,
    "force_scan_called": false,
    "confirm_paper_scan": true,
    "broker_order_submit_allowed": true,
    "broker_order_submit_attempted": false,
    "failure_stage": "preview"
  }
}
""".strip(),
        encoding="utf-8",
    )

    status, summary, _evidence = check_zero_dte_drill(tmp_path)

    assert status == "incomplete"
    assert "did not produce passing order and strategy-recording evidence" in summary


def test_60h_audit_accepts_reconciled_confirmed_zero_dte_scan(tmp_path: Path) -> None:
    (tmp_path / "zero-dte-lottery-drill.json").write_text(
        """
{
  "status": "passed",
  "payload": {
    "force_scan_requested": true,
    "force_scan_called": false,
    "force_scan_evidence_reconciled": true,
    "confirm_paper_scan": true,
    "broker_order_submit_allowed": true,
    "broker_order_submit_attempted": true,
    "strategy_recording_verified": true,
    "reconciled_order": {"id": "order-1"}
  }
}
""".strip(),
        encoding="utf-8",
    )

    status, summary, evidence = check_zero_dte_drill(tmp_path)

    assert status == "proved"
    assert "Confirmed force-scan evidence and strategy recording exist" in summary
    assert evidence["reconciled_order"]["id"] == "order-1"


def test_60h_audit_rejects_reconciled_zero_dte_without_strategy_recording(tmp_path: Path) -> None:
    (tmp_path / "zero-dte-lottery-drill.json").write_text(
        """
{
  "status": "passed",
  "payload": {
    "force_scan_requested": true,
    "force_scan_called": false,
    "force_scan_evidence_reconciled": true,
    "confirm_paper_scan": true,
    "broker_order_submit_allowed": true,
    "broker_order_submit_attempted": true,
    "strategy_recording_verified": false,
    "reconciled_order": {"id": "order-1"}
  }
}
""".strip(),
        encoding="utf-8",
    )

    status, summary, _evidence = check_zero_dte_drill(tmp_path)

    assert status == "incomplete"
    assert "strategy-recording evidence" in summary


def test_60h_audit_accepts_read_only_paper_session_gate(tmp_path: Path) -> None:
    children = [
        {"name": "unattended-status"},
        {"name": "bull-put-real-paper"},
        {"name": "bull-put-readiness"},
        {"name": "zero-dte-lottery-drill"},
        {"name": "bull-put-recovery-drill"},
        {"name": "audit-export"},
        {"name": "consistency-report"},
    ]
    (tmp_path / "paper-session-gate.json").write_text(
        (
            '{"status":"passed","payload":{"children":'
            + json.dumps(children)
            + ',"destructive_actions_executed":false,"broker_order_submit_allowed":false}}'
        ),
        encoding="utf-8",
    )

    status, _summary, evidence = check_paper_session_gate(tmp_path)

    assert status == "proved"
    assert evidence["broker_order_submit_allowed"] is False


def test_60h_audit_accepts_safe_data_hygiene_plan(tmp_path: Path) -> None:
    (tmp_path / "data-hygiene-audit.json").write_text(
        """
{
  "status": "warning",
  "payload": {
    "destructive_actions_executed": false,
    "cleanup_plan": {"safe_by_default": true}
  }
}
""".strip(),
        encoding="utf-8",
    )

    status, _summary, evidence = check_data_hygiene(tmp_path)

    assert status == "proved"
    assert evidence["cleanup_plan"]["safe_by_default"] is True
