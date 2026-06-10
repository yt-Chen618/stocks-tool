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
        "covered_call_auto_propose_disabled",
        "zero_dte_lottery_runtime_policy",
    }
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

    notification = build_unattended_notification(report, action="arm")
    result = dispatch_unattended_notification(
        notification,
        channel="dry-run",
        notification_file=Path("unused.jsonl"),
    )

    assert notification["event_type"] == "unattended_paper_arm"
    assert notification["level"] == "warning"
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
