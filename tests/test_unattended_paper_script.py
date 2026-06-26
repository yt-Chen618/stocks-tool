from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.append(str(SCRIPTS_DIR))

from run_unattended_paper import (  # noqa: E402
    UnattendedPaperError,
    arm_unattended,
    build_strategy_loop_checks,
    build_unattended_notification,
    build_payload,
    dispatch_unattended_notification,
    summarize_snapshot,
    validate_unattended_snapshot,
    validate_strategy_loop_snapshot,
)


def base_snapshot() -> dict:
    return {
        "account_id": "LBPT10087357",
        "mode": "paper",
        "health": {"status": "ok"},
        "controls": {
            "execution_mode": "paper",
            "scheduler_enabled": True,
            "live_trading_enabled": False,
            "paper_execution_allowed": True,
            "live_execution_allowed": False,
            "llm_direct_execution_allowed": False,
            "paper_mandate": {
                "external_account_id": "LBPT10087357",
                "enabled_strategies": ["paper_bull_put_v1", "covered_call_v1", "zero_dte_lottery_v1"],
                "symbol_universe": ["QQQ.US", "SMH.US"],
                "daily_caps": {"bull_put_new_spreads": 1, "zero_dte_lottery_trades": 1},
                "risk_caps": {"zero_dte_max_premium_per_trade": "150"},
                "auto_switches": {"zero_dte_auto_execute": False},
                "manual_pause": False,
                "kill_switch": False,
                "expires_at": None,
            },
            "automation_controls": [
                {
                    "strategy_id": "covered_call_v1",
                    "enabled": True,
                    "auto_propose_enabled": False,
                    "auto_monitor_enabled": True,
                    "auto_lifecycle_enabled": True,
                },
                {
                    "strategy_id": "zero_dte_lottery_v1",
                    "enabled": True,
                    "auto_execute_enabled": False,
                    "scan_interval_seconds": 900,
                },
            ],
        },
        "operator_status": {
            "external_account_id": "LBPT10087357",
            "mode": "paper",
            "generated_at": "2026-06-04T14:32:00Z",
            "status": "pass",
            "ready_for_unattended": True,
            "operator_posture_reason": "All operator posture checks passed.",
            "checks": [
                {
                    "name": "scheduler_recent_runs",
                    "status": "pass",
                    "detail": "Recent scheduler job-run observations are available.",
                    "reason_code": "scheduler_recent_runs_healthy",
                    "reason_detail": "Recent scheduler job-run observations are healthy.",
                }
            ],
            "controls": {},
            "broker_profiles": [
                {
                    "id": "longbridge-paper-LBPT10087357",
                    "broker": "longbridge",
                    "name": "longbridge",
                    "external_account_id": "LBPT10087357",
                    "mode": "paper",
                    "supported_modes": ["paper", "live"],
                    "capabilities": [],
                    "readonly": False,
                    "paper_guard": "config_declared",
                    "configured": True,
                    "credential_status": "ready",
                    "notes": ["Paper guard is declared by local configuration."],
                }
            ],
            "paper_mandate": {
                "external_account_id": "LBPT10087357",
                "enabled_strategies": ["paper_bull_put_v1", "covered_call_v1", "zero_dte_lottery_v1"],
                "symbol_universe": ["QQQ.US", "SMH.US"],
                "daily_caps": {"bull_put_new_spreads": 1, "zero_dte_lottery_trades": 1},
                "risk_caps": {"zero_dte_max_premium_per_trade": "150"},
                "auto_switches": {"zero_dte_auto_execute": False},
                "manual_pause": False,
                "kill_switch": False,
                "expires_at": None,
            },
            "audit_events": [],
            "audit_summary": {"event_count": 1, "warning_count": 0, "by_action": {"advisor_run_card_observed": 1}},
            "consistency_summary": {
                "generated_at": "2026-06-04T14:32:00Z",
                "external_account_id": "LBPT10087357",
                "mode": "paper",
                "strategy": None,
                "limit": 50,
                "status": "pass",
                "check_count": 3,
                "pass_count": 3,
                "warn_count": 0,
                "fail_count": 0,
                "repair_available_count": 0,
                "checks": [],
            },
            "primary_blocker": None,
            "local_repair_available": False,
            "latest_evidence_at": "2026-06-04T14:32:00Z",
            "bull_put_runtime": None,
            "zero_dte_lottery_runtime": None,
            "active_bull_put_spread_count": 1,
            "open_order_count": 0,
            "lifecycle_warnings": [],
            "recent_scheduler_runs": [],
            "recent_scheduler_summaries": [],
        },
        "broker_profiles": [
            {
                "id": "longbridge-paper-LBPT10087357",
                "broker": "longbridge",
                "name": "longbridge",
                "external_account_id": "LBPT10087357",
                "mode": "paper",
                "supported_modes": ["paper", "live"],
                "capabilities": [],
                "readonly": False,
                "paper_guard": "config_declared",
                "configured": True,
                "credential_status": "ready",
                "notes": ["Paper guard is declared by local configuration."],
            }
        ],
        "audit_events": [
            {
                "id": "advisor-run-1",
                "emitted_at": "2026-06-04T14:31:00Z",
                "external_account_id": "LBPT10087357",
                "mode": "paper",
                "actor": "advisor",
                "source": "deepseek",
                "strategy": "strategy_advisor",
                "action": "advisor_run_card_observed",
                "order_ids": [],
                "summary": "Advisor run observed.",
                "payload": {},
            }
        ],
        "audit_summary": {
            "generated_at": "2026-06-04T14:32:00Z",
            "external_account_id": "LBPT10087357",
            "mode": "paper",
            "since": None,
            "limit": 200,
            "event_count": 1,
            "warning_count": 0,
            "groups": [
                {
                    "external_account_id": "LBPT10087357",
                    "mode": "paper",
                    "source": "deepseek",
                    "action": "advisor_run_card_observed",
                    "strategy": "strategy_advisor",
                    "warning_code": None,
                    "event_origin": "synthetic",
                    "count": 1,
                    "latest_emitted_at": "2026-06-04T14:31:00Z",
                }
            ],
        },
        "runtime": {
            "external_account_id": "LBPT10087357",
            "mode": "paper",
            "auto_entry_enabled": False,
            "manual_pause": False,
            "kill_switch_active": False,
            "next_action": "resolve_runtime_controls",
        },
        "spreads": [
            {
                "id": "spread-1",
                "underlying_symbol": "QQQ.US",
                "status": "open",
                "long_entry_order_id": "order-1",
                "raw_payload": {"monitor": {"should_close": False}},
            },
            {
                "id": "spread-2",
                "underlying_symbol": "QQQ.US",
                "status": "closed",
            },
        ],
        "covered_call_activity": {
            "summary": {"executed_positions": 0},
            "lifecycle_tasks": [],
        },
        "zero_dte_lottery_runtime": {
            "strategy_id": "zero_dte_lottery_v1",
            "external_account_id": "LBPT10087357",
            "mode": "paper",
            "enabled": True,
            "auto_execute_enabled": False,
            "scan_interval_seconds": 900,
            "scan_window_start": "10:00 ET",
            "scan_window_end": "14:30 ET",
            "max_premium_per_trade": "150",
            "contracts_per_trade": 1,
            "max_trades_per_day": 1,
            "symbols": ["QQQ.US"],
        },
        "account_snapshot": {
            "account_id": "LBPT10087357",
            "positions": [
                {
                    "symbol": "QQQ.US",
                    "asset_type": "stock",
                    "quantity": "100.0000",
                    "market_value": "73502.0000",
                    "unrealized_pnl": "-690.0000",
                    "average_cost": "741.9200",
                }
            ],
        },
        "orders": [
            {
                "id": "order-1",
                "symbol": "QQQ.US",
                "asset_type": "stock",
                "side": "buy",
                "status": "filled",
                "mode": "paper",
                "raw_payload": {"remote_order": {"status": "FILLED"}},
            }
        ],
        "executions": [
            {
                "id": "execution-1",
                "order_id": "order-1",
                "symbol": "QQQ.US",
                "side": "buy",
                "quantity": 1,
                "price": "735.00",
                "executed_at": "2026-06-04T14:31:00Z",
            }
        ],
        "journals": [
            {
                "id": "journal-1",
                "symbol": "QQQ.US",
                "entry_type": "execution",
                "title": "Paper order filled",
                "order_id": "order-1",
                "execution_id": "execution-1",
                "created_at": "2026-06-04T14:32:00Z",
            }
        ],
        "pre_open_runs": [
            {
                "id": "run-1",
                "target_session_date": "2026-06-04",
                "review_status": "mixed",
                "review_summary": "Opening follow-through stayed mixed.",
                "raw_payload": {"journal": {"assessment_logged_at": "ignored"}},
                "assessment": {
                    "summary": "The proxy set is mixed.",
                    "freshness_status": "partial",
                    "signals": [{"symbol": "QQQ.US"}],
                },
            }
        ],
    }


def test_validate_unattended_snapshot_accepts_conservative_paper_mode() -> None:
    validate_unattended_snapshot(base_snapshot())


def test_validate_unattended_snapshot_rejects_live_trading() -> None:
    snapshot = base_snapshot()
    snapshot["controls"]["live_trading_enabled"] = True

    with pytest.raises(UnattendedPaperError, match="Live trading"):
        validate_unattended_snapshot(snapshot)


def test_validate_unattended_snapshot_requires_scheduler() -> None:
    snapshot = base_snapshot()
    snapshot["controls"]["scheduler_enabled"] = False

    with pytest.raises(UnattendedPaperError, match="scheduler"):
        validate_unattended_snapshot(snapshot)


def test_validate_unattended_snapshot_rejects_operator_posture_failure() -> None:
    snapshot = base_snapshot()
    snapshot["operator_status"]["status"] = "fail"
    snapshot["operator_status"]["ready_for_unattended"] = False
    snapshot["operator_status"]["operator_posture_reason"] = "Manual action required."

    with pytest.raises(UnattendedPaperError, match="operator_posture_ready"):
        validate_unattended_snapshot(snapshot)


def test_validate_unattended_snapshot_rejects_bad_broker_profile_guard() -> None:
    snapshot = base_snapshot()
    snapshot["broker_profiles"][0]["paper_guard"] = "unknown"
    snapshot["operator_status"]["broker_profiles"][0]["paper_guard"] = "unknown"

    with pytest.raises(UnattendedPaperError, match="broker_profile_paper_guard"):
        validate_unattended_snapshot(snapshot)


def test_validate_unattended_snapshot_rejects_paused_paper_mandate() -> None:
    snapshot = base_snapshot()
    snapshot["operator_status"]["paper_mandate"]["kill_switch"] = True

    with pytest.raises(UnattendedPaperError, match="paper_mandate_allows_monitoring"):
        validate_unattended_snapshot(snapshot)


def test_validate_unattended_snapshot_rejects_covered_call_auto_propose() -> None:
    snapshot = base_snapshot()
    snapshot["controls"]["automation_controls"][0]["auto_propose_enabled"] = True

    with pytest.raises(UnattendedPaperError, match="covered_call_auto_propose_disabled"):
        validate_unattended_snapshot(snapshot)


def test_validate_strategy_loop_snapshot_allows_resume_mode_auto_entry_warning() -> None:
    snapshot = base_snapshot()
    snapshot["runtime"]["auto_entry_enabled"] = True

    validate_strategy_loop_snapshot(snapshot)
    checks = build_strategy_loop_checks(snapshot)

    auto_entry_check = next(check for check in checks if check["name"] == "bull_put_auto_entry_disabled_for_unattended")
    assert auto_entry_check["status"] == "warn"


def test_validate_unattended_snapshot_rejects_missing_order_links() -> None:
    snapshot = base_snapshot()
    snapshot["orders"] = []

    with pytest.raises(UnattendedPaperError, match="bull_put_spread_order_links"):
        validate_unattended_snapshot(snapshot)


def test_validate_unattended_snapshot_rejects_canceled_stop_loss_close_order() -> None:
    snapshot = base_snapshot()
    spread = snapshot["spreads"][0]
    spread.update(
        {
            "short_symbol": "QQQ260626P708000.US",
            "short_entry_order_id": "short-entry-order",
            "short_exit_order_id": "short-exit-order",
            "exit_reason": "stop_loss",
            "raw_payload": {
                "monitor": {
                    "should_close": True,
                    "exit_reason": "stop_loss",
                }
            },
        }
    )
    snapshot["orders"] = [
        *snapshot["orders"],
        {
            "id": "short-entry-order",
            "symbol": "QQQ260626P708000.US",
            "asset_type": "option",
            "side": "sell",
            "status": "filled",
            "mode": "paper",
        },
        {
            "id": "short-exit-order",
            "symbol": "QQQ260626P708000.US",
            "asset_type": "option",
            "side": "buy",
            "status": "canceled",
            "mode": "paper",
        },
    ]

    with pytest.raises(UnattendedPaperError, match="bull_put_close_order_state"):
        validate_unattended_snapshot(snapshot)

    checks = build_strategy_loop_checks(snapshot)
    close_order_check = next(check for check in checks if check["name"] == "bull_put_close_order_state")
    assert close_order_check["status"] == "fail"

    payload = build_payload(snapshot)
    assert payload["strategy_loop_summary"]["check_status"] == "failed"
    warning = payload["monitorable_spreads"][0]["lifecycle_warning"]
    assert warning["code"] == "close_order_canceled_manual_action_needed"
    assert warning["manual_action_required"] is True
    assert warning["order_id"] == "short-exit-order"


def test_unattended_payload_reports_normalized_bull_put_lifecycle_warning() -> None:
    snapshot = base_snapshot()
    spread = snapshot["spreads"][0]
    spread.update(
        {
            "short_symbol": "QQQ260626P708000.US",
            "short_entry_order_id": "short-entry-order",
            "short_exit_order_id": "short-exit-order",
            "exit_reason": "stop_loss",
            "raw_payload": None,
            "lifecycle_warning_code": "close_order_canceled_manual_action_needed",
            "manual_action_required": True,
            "latest_monitor_should_close": True,
            "latest_close_order_status": "canceled",
            "next_monitor_after": "2026-06-15T14:55:00+00:00",
        }
    )
    snapshot["orders"] = [
        *snapshot["orders"],
        {
            "id": "short-entry-order",
            "symbol": "QQQ260626P708000.US",
            "asset_type": "option",
            "side": "sell",
            "status": "filled",
            "mode": "paper",
        },
        {
            "id": "short-exit-order",
            "symbol": "QQQ260626P708000.US",
            "asset_type": "option",
            "side": "buy",
            "status": "canceled",
            "mode": "paper",
        },
    ]

    checks = build_strategy_loop_checks(snapshot)
    close_order_check = next(check for check in checks if check["name"] == "bull_put_close_order_state")
    assert close_order_check["status"] == "fail"

    warning = build_payload(snapshot)["monitorable_spreads"][0]["lifecycle_warning"]
    assert warning["code"] == "close_order_canceled_manual_action_needed"
    assert warning["order_status"] == "canceled"


def test_validate_unattended_snapshot_rejects_execution_or_journal_drift() -> None:
    snapshot = base_snapshot()
    snapshot["executions"][0]["order_id"] = "missing-order"

    with pytest.raises(UnattendedPaperError, match="execution_order_links"):
        validate_unattended_snapshot(snapshot)

    snapshot = base_snapshot()
    snapshot["journals"][0]["execution_id"] = "missing-execution"

    with pytest.raises(UnattendedPaperError, match="journal_links"):
        validate_unattended_snapshot(snapshot)


def test_validate_unattended_snapshot_rejects_zero_dte_policy_drift() -> None:
    snapshot = base_snapshot()
    snapshot["zero_dte_lottery_runtime"]["max_premium_per_trade"] = "200"

    with pytest.raises(UnattendedPaperError, match="zero_dte_lottery_runtime_policy"):
        validate_unattended_snapshot(snapshot)


def test_validate_unattended_snapshot_rejects_zero_dte_daily_order_overage() -> None:
    snapshot = base_snapshot()
    lottery_order = {
        "id": "lottery-order-1",
        "symbol": "QQQ260604C736000.US",
        "asset_type": "option",
        "side": "buy",
        "status": "submitted",
        "mode": "paper",
        "submitted_at": "2026-06-04T14:30:00Z",
        "raw_payload": {"submission_request": {"remark": "zero_dte_lottery_v1"}},
    }
    snapshot["orders"] = [
        *snapshot["orders"],
        lottery_order,
        {**lottery_order, "id": "lottery-order-2"},
    ]

    with pytest.raises(UnattendedPaperError, match="zero_dte_lottery_daily_order_guard"):
        validate_unattended_snapshot(snapshot)


def test_arm_summary_reports_monitorable_spreads() -> None:
    summary = summarize_snapshot("arm", base_snapshot())

    assert "new bull put entries are disabled" in summary
    assert "1 monitorable spread" in summary
    assert "zero-DTE lottery auto-order is off" in summary


def test_payload_filters_to_monitorable_spreads() -> None:
    payload = build_payload(base_snapshot())

    assert payload["strategy_loop_summary"]["check_status"] == "passed"
    assert payload["strategy_loop_summary"]["recent_execution_count"] == 1
    assert payload["strategy_loop_summary"]["recent_journal_count"] == 1
    assert {check["name"] for check in payload["strategy_loop_checks"]} >= {
        "paper_first_boundary",
        "broker_profile_paper_guard",
        "operator_posture_ready",
        "paper_mandate_allows_monitoring",
        "operator_audit_summary_available",
        "covered_call_auto_propose_disabled",
        "zero_dte_lottery_runtime_policy",
    }
    assert payload["operator_status"]["status"] == "pass"
    assert payload["consistency_summary"]["status"] == "pass"
    assert payload["primary_blocker"] is None
    assert payload["local_repair_available"] is False
    assert payload["latest_evidence_at"] == "2026-06-04T14:32:00Z"
    assert payload["broker_profiles"][0]["paper_guard"] == "config_declared"
    assert payload["paper_mandate"]["external_account_id"] == "LBPT10087357"
    assert payload["audit_events"][0]["action"] == "advisor_run_card_observed"
    assert payload["operator_posture_reason"] == "All operator posture checks passed."
    assert payload["strategy_loop_summary"]["operator_posture_status"] == "pass"
    assert payload["strategy_loop_summary"]["consistency_status"] == "pass"
    assert payload["strategy_loop_summary"]["operator_reason_details"] == {
        "scheduler_recent_runs_healthy": "Recent scheduler job-run observations are healthy."
    }
    assert payload["operator_reason_details"] == {
        "scheduler_recent_runs_healthy": "Recent scheduler job-run observations are healthy."
    }
    assert payload["strategy_loop_summary"]["audit_event_count"] == 1
    assert [spread["id"] for spread in payload["monitorable_spreads"]] == ["spread-1"]
    assert payload["monitorable_spreads"][0]["monitor"] == {"should_close": False}
    assert payload["recent_orders"] == [
        {
                "id": "order-1",
                "external_order_id": None,
                "symbol": "QQQ.US",
                "asset_type": "stock",
                "side": "buy",
                "quantity": None,
                "order_type": None,
                "status": "filled",
            "limit_price": None,
            "submitted_at": None,
            "updated_at": None,
        }
    ]
    assert "average_cost" not in payload["latest_account_snapshot"]["positions"][0]
    assert payload["latest_pre_open_run"]["id"] == "run-1"
    assert "raw_payload" not in payload["latest_pre_open_run"]
    assert "signals" not in payload["latest_pre_open_run"]["assessment"]
    assert payload["zero_dte_lottery_runtime"]["auto_execute_enabled"] is False
    assert payload["recent_executions"][0]["order_id"] == "order-1"
    assert payload["recent_journals"][0]["execution_id"] == "execution-1"


def test_arm_unattended_can_enable_zero_dte_lottery_auto_order() -> None:
    state = {"zero_auto": False}
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        snapshot = base_snapshot()
        if request.method == "POST" and request.url.path == "/strategies/bull-put/runtime/LBPT10087357":
            return httpx.Response(200, json=snapshot["runtime"])
        if request.method == "POST" and request.url.path == "/strategies/zero-dte-lottery/runtime/LBPT10087357":
            assert json.loads(request.content) == {"auto_execute_enabled": True}
            state["zero_auto"] = True
            runtime = snapshot["zero_dte_lottery_runtime"]
            runtime["auto_execute_enabled"] = True
            return httpx.Response(200, json=runtime)
        if request.method == "GET" and request.url.path == "/health":
            return httpx.Response(200, json=snapshot["health"])
        if request.method == "GET" and request.url.path == "/strategies/controls":
            return httpx.Response(200, json=snapshot["controls"])
        if request.method == "GET" and request.url.path == "/ops/unattended-status":
            operator_status = snapshot["operator_status"]
            operator_status["paper_mandate"]["auto_switches"]["zero_dte_auto_execute"] = state["zero_auto"]
            return httpx.Response(200, json=operator_status)
        if request.method == "GET" and request.url.path == "/ops/audit":
            return httpx.Response(200, json=snapshot["audit_events"])
        if request.method == "GET" and request.url.path == "/ops/audit/summary":
            return httpx.Response(200, json=snapshot["audit_summary"])
        if request.method == "GET" and request.url.path == "/brokers/profiles":
            return httpx.Response(200, json=snapshot["broker_profiles"])
        if request.method == "GET" and request.url.path == "/strategies/bull-put/runtime":
            return httpx.Response(200, json=snapshot["runtime"])
        if request.method == "GET" and request.url.path == "/strategies/bull-put/spreads":
            return httpx.Response(200, json=snapshot["spreads"])
        if request.method == "GET" and request.url.path == "/strategies/covered-call/activity":
            return httpx.Response(200, json=snapshot["covered_call_activity"])
        if request.method == "GET" and request.url.path == "/strategies/zero-dte-lottery/runtime":
            runtime = snapshot["zero_dte_lottery_runtime"]
            runtime["auto_execute_enabled"] = state["zero_auto"]
            return httpx.Response(200, json=runtime)
        if request.method == "GET" and request.url.path == "/account-snapshots/latest":
            return httpx.Response(200, json=snapshot["account_snapshot"])
        if request.method == "GET" and request.url.path == "/orders":
            return httpx.Response(200, json=snapshot["orders"])
        if request.method == "GET" and request.url.path == "/executions":
            return httpx.Response(200, json=snapshot["executions"])
        if request.method == "GET" and request.url.path == "/journals":
            return httpx.Response(200, json=snapshot["journals"])
        if request.method == "GET" and request.url.path == "/strategies/pre-open-runs":
            return httpx.Response(200, json=snapshot["pre_open_runs"])
        return httpx.Response(404, json={"detail": request.url.path})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://testserver") as client:
        snapshot = arm_unattended(
            client,
            account_id="LBPT10087357",
            mode="paper",
            zero_dte_lottery_auto_order="on",
        )

    assert snapshot["zero_dte_lottery_runtime"]["auto_execute_enabled"] is True
    assert snapshot["zero_dte_lottery_runtime_update"]["auto_execute_enabled"] is True
    assert any(
        call.method == "POST" and call.url.path == "/strategies/zero-dte-lottery/runtime/LBPT10087357"
        for call in calls
    )


def test_unattended_notification_dry_run_reports_warning_when_lottery_auto_order_is_on() -> None:
    snapshot = base_snapshot()
    snapshot["zero_dte_lottery_runtime"]["auto_execute_enabled"] = True
    payload = build_payload(snapshot)
    report = {
        "workflow": "unattended-paper-arm",
        "status": "passed",
        "mode": "paper",
        "target": "http://testserver",
        "summary": "Unattended paper mode armed.",
        "generated_at": "2026-06-10T10:00:00Z",
        "payload": payload,
    }

    notification = build_unattended_notification(report, action="arm", run_id="run-20260618")
    result = dispatch_unattended_notification(
        notification,
        channel="dry-run",
        notification_file=Path("unused.jsonl"),
    )

    assert notification["event_type"] == "unattended_paper_arm"
    assert notification["run_id"] == "run-20260618"
    assert notification["level"] == "warning"
    assert notification["severity"] == "warning"
    assert notification["reason_codes"] == ["scheduler_recent_runs_healthy"]
    assert notification["broker_submit_allowed"] is False
    assert notification["local_repair_available"] is False
    assert notification["recommended_action"].startswith("Verify zero-DTE lottery auto-ordering")
    assert notification["metrics"]["zero_dte_lottery_auto_order_enabled"] is True
    assert "email" in notification["reserved_external_channels"]
    assert result["channel"] == "dry-run"
    assert result["emitted"] is False


def test_unattended_notification_file_channel_writes_jsonl(tmp_path: Path) -> None:
    report = {
        "workflow": "unattended-paper-status",
        "status": "failed",
        "mode": "paper",
        "target": "http://testserver",
        "summary": "Unattended paper workflow failed.",
        "generated_at": "2026-06-10T10:00:00Z",
        "payload": {"account_id": "LBPT10087357"},
    }
    notification = build_unattended_notification(report, action="status")
    output_path = tmp_path / "notifications.jsonl"

    result = dispatch_unattended_notification(
        notification,
        channel="file",
        notification_file=output_path,
    )

    assert result["emitted"] is True
    line = output_path.read_text(encoding="utf-8").strip()
    payload = json.loads(line)
    assert payload["level"] == "critical"
    assert payload["account_id"] == "LBPT10087357"


def test_unattended_notification_file_channel_rotates_large_jsonl(tmp_path: Path) -> None:
    output_path = tmp_path / "notifications.jsonl"
    output_path.write_text('{"old": true}\n', encoding="utf-8")
    notification = {
        "schema_version": "unattended_paper_notification_v1",
        "event_type": "unattended_paper_status",
        "run_id": "run-rotation",
        "level": "info",
    }

    result = dispatch_unattended_notification(
        notification,
        channel="file",
        notification_file=output_path,
        max_file_bytes=1,
    )

    assert result["emitted"] is True
    assert result["run_id"] == "run-rotation"
    assert result["rotated_path"] is not None
    rotated_path = Path(result["rotated_path"])
    assert rotated_path.exists()
    assert json.loads(rotated_path.read_text(encoding="utf-8").strip()) == {"old": True}
    current_payload = json.loads(output_path.read_text(encoding="utf-8").strip())
    assert current_payload["run_id"] == "run-rotation"


def test_unattended_notification_reports_local_repair_availability() -> None:
    notification = build_unattended_notification(
        {
            "status": "passed",
            "mode": "paper",
            "summary": "Unattended paper status.",
            "generated_at": "2026-06-04T14:32:00Z",
            "payload": {
                "account_id": "LBPT10087357",
                "operator_reason_codes": ["local_repair_available"],
                "primary_blocker": "local_repair_available",
                "local_repair_available": True,
                "strategy_loop_summary": {
                    "account_id": "LBPT10087357",
                    "failed_checks": [],
                    "warning_checks": [],
                },
            },
        },
        action="status",
    )

    assert notification["local_repair_available"] is True
    assert notification["primary_blocker"] == "local_repair_available"
    assert notification["reason_codes"] == ["local_repair_available"]
    assert "/ops/consistency" in notification["recommended_action"]


def test_unattended_notification_failed_report_points_to_error() -> None:
    notification = build_unattended_notification(
        {
            "status": "failed",
            "mode": "paper",
            "summary": "Unattended paper workflow failed.",
            "generated_at": "2026-06-04T14:32:00Z",
            "payload": {"account_id": "LBPT10087357"},
            "error": "operator_posture_ready: bull put monitor failed",
        },
        action="status",
    )

    assert notification["level"] == "critical"
    assert notification["primary_blocker"] == "operator_posture_ready: bull put monitor failed"
    assert notification["recommended_action"] == "Review unattended failure: operator_posture_ready: bull put monitor failed"


def test_unattended_notification_respects_min_level() -> None:
    notification = {
        "schema_version": "unattended_paper_notification_v1",
        "event_type": "unattended_paper_status",
        "level": "info",
    }

    result = dispatch_unattended_notification(
        notification,
        channel="dry-run",
        notification_file=Path("unused.jsonl"),
        min_level="warning",
    )

    assert result["emitted"] is False
    assert "below minimum" in result["reason"]
