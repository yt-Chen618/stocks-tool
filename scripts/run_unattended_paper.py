from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from decimal import Decimal, InvalidOperation

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import httpx
from regression_common import build_report, emit_report
from stocks_tool.application.services.strategy_lifecycle import bull_put_close_order_warning

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ACCOUNT_ID = "LBPT10087357"
MONITORABLE_SPREAD_STATUSES = {"open", "exit_pending_short", "exit_pending_long"}
ZERO_DTE_STRATEGY_ID = "zero_dte_lottery_v1"


class UnattendedPaperError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Arm, inspect, or resume the local paper unattended mode. "
            "This workflow disables new bull put entries for overnight operation while leaving existing paper "
            "monitoring, lifecycle reconciliation, and explicitly armed lottery automation to the FastAPI "
            "background scheduler."
        )
    )
    parser.add_argument(
        "action",
        choices=("arm", "status", "resume"),
        help="arm disables new bull put entries, status prints a morning/evening summary, resume re-enables entries.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID)
    parser.add_argument("--mode", default="paper")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument(
        "--notification-channel",
        choices=("none", "dry-run", "console", "file"),
        default="none",
        help=(
            "Optional local notification adapter. dry-run records the payload in the report, console writes JSON to stderr, "
            "and file appends JSONL to --notification-file. Email/push/SMS are intentionally not active yet."
        ),
    )
    parser.add_argument(
        "--notification-file",
        type=Path,
        default=Path("artifacts/unattended-paper-notifications.jsonl"),
        help="JSONL notification output path when --notification-channel=file.",
    )
    parser.add_argument(
        "--notification-min-level",
        choices=("info", "warning", "critical"),
        default="info",
        help="Minimum notification level to emit.",
    )
    parser.add_argument(
        "--zero-dte-lottery-auto-order",
        choices=("leave", "on", "off"),
        default="leave",
        help=(
            "For arm/resume, explicitly enable or disable zero-DTE lottery paper auto-ordering. "
            "The default leaves the current API runtime setting unchanged."
        ),
    )
    return parser.parse_args()


def require_json(response: httpx.Response) -> Any:
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise UnattendedPaperError(f"{response.request.method} {response.request.url} returned non-JSON.") from exc
    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        raise UnattendedPaperError(f"{response.request.method} {response.request.url} returned {response.status_code}: {detail}")
    return payload


def get_json(client: httpx.Client, path: str, *, params: dict[str, Any] | None = None) -> Any:
    return require_json(client.get(path, params=params))


def post_json(
    client: httpx.Client,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> Any:
    return require_json(client.post(path, params=params, json=body or {}))


def collect_snapshot(client: httpx.Client, *, account_id: str, mode: str) -> dict[str, Any]:
    return {
        "account_id": account_id,
        "mode": mode,
        "health": get_json(client, "/health"),
        "controls": get_json(
            client,
            "/strategies/controls",
            params={"external_account_id": account_id, "mode": mode},
        ),
        "operator_status": get_json(
            client,
            "/ops/unattended-status",
            params={"external_account_id": account_id, "mode": mode},
        ),
        "audit_events": get_json(
            client,
            "/ops/audit",
            params={"external_account_id": account_id, "limit": 20},
        ),
        "audit_summary": get_json(
            client,
            "/ops/audit/summary",
            params={"external_account_id": account_id, "mode": mode, "limit": 200},
        ),
        "broker_profiles": get_json(client, "/brokers/profiles"),
        "runtime": get_json(
            client,
            "/strategies/bull-put/runtime",
            params={"external_account_id": account_id, "mode": mode},
        ),
        "spreads": get_json(
            client,
            "/strategies/bull-put/spreads",
            params={"external_account_id": account_id, "mode": mode, "limit": 10},
        ),
        "covered_call_activity": get_json(
            client,
            "/strategies/covered-call/activity",
            params={"external_account_id": account_id, "mode": mode, "limit": 10},
        ),
        "zero_dte_lottery_runtime": get_json(
            client,
            "/strategies/zero-dte-lottery/runtime",
            params={"external_account_id": account_id, "mode": mode},
        ),
        "account_snapshot": get_json(
            client,
            "/account-snapshots/latest",
            params={"external_account_id": account_id},
        ),
        "orders": get_json(
            client,
            "/orders",
            params={"external_account_id": account_id},
        ),
        "executions": get_json(
            client,
            "/executions",
            params={"external_account_id": account_id},
        ),
        "journals": get_json(
            client,
            "/journals",
            params={"external_account_id": account_id},
        ),
        "pre_open_runs": get_json(
            client,
            "/strategies/pre-open-runs",
            params={"external_account_id": account_id, "limit": 1},
        ),
    }


def update_zero_dte_lottery_auto_order(
    client: httpx.Client,
    *,
    account_id: str,
    mode: str,
    setting: str,
) -> dict[str, Any] | None:
    if setting == "leave":
        return None
    return post_json(
        client,
        f"/strategies/zero-dte-lottery/runtime/{account_id}",
        params={"mode": mode},
        body={"auto_execute_enabled": setting == "on"},
    )


def arm_unattended(
    client: httpx.Client,
    *,
    account_id: str,
    mode: str,
    zero_dte_lottery_auto_order: str = "leave",
) -> dict[str, Any]:
    update = post_json(
        client,
        f"/strategies/bull-put/runtime/{account_id}",
        params={"mode": mode},
        body={
            "auto_entry_enabled": False,
            "manual_pause": False,
            "kill_switch_active": False,
            "paused_symbols": [],
        },
    )
    lottery_update = update_zero_dte_lottery_auto_order(
        client,
        account_id=account_id,
        mode=mode,
        setting=zero_dte_lottery_auto_order,
    )
    snapshot = collect_snapshot(client, account_id=account_id, mode=mode)
    snapshot["runtime_update"] = update
    snapshot["zero_dte_lottery_runtime_update"] = lottery_update
    validate_unattended_snapshot(snapshot)
    return snapshot


def resume_entries(
    client: httpx.Client,
    *,
    account_id: str,
    mode: str,
    zero_dte_lottery_auto_order: str = "leave",
) -> dict[str, Any]:
    update = post_json(
        client,
        f"/strategies/bull-put/runtime/{account_id}",
        params={"mode": mode},
        body={"auto_entry_enabled": True},
    )
    lottery_update = update_zero_dte_lottery_auto_order(
        client,
        account_id=account_id,
        mode=mode,
        setting=zero_dte_lottery_auto_order,
    )
    snapshot = collect_snapshot(client, account_id=account_id, mode=mode)
    snapshot["runtime_update"] = update
    snapshot["zero_dte_lottery_runtime_update"] = lottery_update
    return snapshot


def validate_unattended_snapshot(snapshot: dict[str, Any]) -> None:
    validate_strategy_loop_snapshot(snapshot, require_unattended_armed=True)


def validate_strategy_loop_snapshot(
    snapshot: dict[str, Any],
    *,
    require_unattended_armed: bool = False,
) -> None:
    failed = [
        check
        for check in build_strategy_loop_checks(
            snapshot,
            require_unattended_armed=require_unattended_armed,
        )
        if check["status"] == "fail" and check["blocking"]
    ]
    if failed:
        first = failed[0]
        raise UnattendedPaperError(f"{first['name']}: {first['detail']}")


def build_strategy_loop_checks(
    snapshot: dict[str, Any],
    *,
    require_unattended_armed: bool = False,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, detail: str, *, blocking: bool = True) -> None:
        checks.append(
            {
                "name": name,
                "status": status,
                "detail": detail,
                "blocking": blocking,
            }
        )

    account_id = snapshot.get("account_id")
    mode = snapshot.get("mode") or "paper"
    health = snapshot.get("health") or {}
    controls = snapshot.get("controls") or {}
    operator_status = snapshot.get("operator_status") or {}
    broker_profiles = _snapshot_broker_profiles(snapshot)
    paper_mandate = _snapshot_paper_mandate(snapshot)
    audit_summary = _snapshot_audit_summary(snapshot)
    runtime = snapshot.get("runtime") or {}
    orders = snapshot.get("orders") or []
    executions = snapshot.get("executions") or []
    journals = snapshot.get("journals") or []
    covered_call_activity = snapshot.get("covered_call_activity") or {}
    zero_dte_runtime = snapshot.get("zero_dte_lottery_runtime") or {}

    add(
        "local_api_health",
        "pass" if health.get("status") == "ok" else "fail",
        "Local API health check is ok." if health.get("status") == "ok" else "Local API health check is not ok.",
    )

    paper_first_ok = (
        controls.get("execution_mode", mode) == "paper"
        and not bool(controls.get("live_trading_enabled"))
        and bool(controls.get("paper_execution_allowed", True))
        and not bool(controls.get("live_execution_allowed", False))
        and not bool(controls.get("llm_direct_execution_allowed", False))
    )
    paper_first_failure = (
        "Live trading is enabled; unattended paper workflow refuses to arm."
        if controls.get("live_trading_enabled")
        else "Execution controls do not prove a paper-first boundary."
    )
    add(
        "paper_first_boundary",
        "pass" if paper_first_ok else "fail",
        "Execution controls are paper-first and block live/LLM direct execution."
        if paper_first_ok
        else paper_first_failure,
    )

    operator_ready = (
        isinstance(operator_status, dict)
        and operator_status.get("status") != "fail"
        and operator_status.get("ready_for_unattended") is not False
    )
    add(
        "operator_posture_ready",
        "pass" if operator_ready else "fail",
        (
            operator_status.get("operator_posture_reason")
            or "Operator status reports paper unattended posture is ready."
        )
        if operator_ready
        else (
            operator_status.get("operator_posture_reason")
            or "Operator status is missing or reports a failing unattended posture."
        ),
    )

    broker_profile = _selected_broker_profile(
        broker_profiles=broker_profiles,
        account_id=account_id,
    )
    broker_profile_ok = (
        broker_profile is not None
        and broker_profile.get("mode", mode) == "paper"
        and broker_profile.get("paper_guard") == "config_declared"
        and broker_profile.get("external_account_id") in {None, account_id}
    )
    add(
        "broker_profile_paper_guard",
        "pass" if broker_profile_ok else "fail",
        "Broker profile resolves to the selected paper account with config-declared paper guard."
        if broker_profile_ok
        else "Broker profile does not prove the selected paper account and config-declared paper guard.",
    )

    mandate_ok = (
        isinstance(paper_mandate, dict)
        and paper_mandate.get("external_account_id") in {None, account_id}
        and paper_mandate.get("kill_switch") is not True
        and paper_mandate.get("manual_pause") is not True
    )
    add(
        "paper_mandate_allows_monitoring",
        "pass" if mandate_ok else "fail",
        "Paper mandate matches the selected account and leaves monitoring unpaused."
        if mandate_ok
        else "Paper mandate is missing, targets another account, or has manual pause / kill switch active.",
    )

    audit_summary_present = isinstance(audit_summary, dict)
    audit_warning_count = int(audit_summary.get("warning_count") or 0) if audit_summary_present else 0
    add(
        "operator_audit_summary_available",
        "warn" if audit_summary_present and audit_warning_count else ("pass" if audit_summary_present else "fail"),
        (
            f"Operator audit summary is available with {audit_warning_count} warning event(s)."
            if audit_summary_present and audit_warning_count
            else "Operator audit summary is available."
            if audit_summary_present
            else "Operator audit summary is missing from unattended posture."
        ),
        blocking=not audit_summary_present,
    )

    add(
        "scheduler_enabled",
        "pass" if controls.get("scheduler_enabled") else "fail",
        "Background scheduler is enabled."
        if controls.get("scheduler_enabled")
        else "Background scheduler is disabled; unattended monitoring would not run.",
    )

    covered_control = _automation_control(controls, "covered_call_v1")
    covered_auto_propose = bool((covered_control or {}).get("auto_propose_enabled"))
    add(
        "covered_call_auto_propose_disabled",
        "pass" if not covered_auto_propose else "fail",
        "Covered-call auto-propose is disabled."
        if not covered_auto_propose
        else "Covered-call auto-propose is enabled; unattended mode should not create new covered-call candidates implicitly.",
    )

    runtime_account_ok = runtime.get("external_account_id") in {None, account_id}
    runtime_mode_ok = runtime.get("mode") in {None, mode}
    add(
        "bull_put_runtime_matches_account",
        "pass" if runtime_account_ok and runtime_mode_ok else "fail",
        "Bull put runtime belongs to the selected account/mode."
        if runtime_account_ok and runtime_mode_ok
        else "Bull put runtime account or mode does not match the selected paper account.",
    )

    bull_put_armed_ok = not bool(runtime.get("auto_entry_enabled"))
    add(
        "bull_put_auto_entry_disabled_for_unattended",
        "pass" if bull_put_armed_ok else ("fail" if require_unattended_armed else "warn"),
        "Bull put auto-entry is disabled for unattended operation."
        if bull_put_armed_ok
        else "Bull put auto-entry is enabled; verify this is intentional before leaving the app unattended.",
        blocking=require_unattended_armed,
    )

    monitoring_unblocked = not bool(runtime.get("manual_pause")) and not bool(runtime.get("kill_switch_active"))
    add(
        "bull_put_monitoring_unblocked",
        "pass" if monitoring_unblocked else "fail",
        "Runtime pause and kill switch are clear, so existing spread monitoring can proceed."
        if monitoring_unblocked
        else "Runtime pause or kill switch is active; existing spread monitoring may be blocked.",
    )

    known_order_ids = {
        str(order.get("id"))
        for order in orders
        if isinstance(order, dict) and order.get("id") is not None
    }
    orders_by_id = {
        str(order.get("id")): order
        for order in orders
        if isinstance(order, dict) and order.get("id") is not None
    }
    known_execution_ids = {
        str(execution.get("id"))
        for execution in executions
        if isinstance(execution, dict) and execution.get("id") is not None
    }
    missing_spread_orders = _missing_linked_orders(
        snapshot.get("spreads") or [],
        known_order_ids,
    )
    add(
        "bull_put_spread_order_links",
        "pass" if not missing_spread_orders else "fail",
        "Monitorable bull put spread order links are present in the order list."
        if not missing_spread_orders
        else f"Missing linked bull put order ids: {', '.join(missing_spread_orders)}.",
    )

    close_order_warnings = _bull_put_close_order_warnings(
        snapshot.get("spreads") or [],
        orders_by_id,
    )
    add(
        "bull_put_close_order_state",
        "pass" if not close_order_warnings else "fail",
        "Bull put close-order state is consistent with the latest monitor snapshot."
        if not close_order_warnings
        else "Bull put close order canceled/rejected while the latest monitor still requires close; "
        f"manual action is required for spread(s): {', '.join(close_order_warnings)}.",
    )

    missing_lifecycle_orders = _missing_lifecycle_orders(
        covered_call_activity.get("lifecycle_tasks") or [],
        known_order_ids,
    )
    add(
        "covered_call_lifecycle_order_links",
        "pass" if not missing_lifecycle_orders else "fail",
        "Covered-call lifecycle task order links are present in the order list."
        if not missing_lifecycle_orders
        else f"Missing covered-call lifecycle order ids: {', '.join(missing_lifecycle_orders)}.",
    )

    missing_execution_orders = [
        str(execution.get("order_id"))
        for execution in executions
        if isinstance(execution, dict)
        and execution.get("order_id") is not None
        and str(execution.get("order_id")) not in known_order_ids
    ]
    add(
        "execution_order_links",
        "pass" if not missing_execution_orders else "fail",
        "Execution records link to known local orders."
        if not missing_execution_orders
        else f"Execution records reference missing order ids: {', '.join(sorted(set(missing_execution_orders)))}.",
    )

    missing_journal_links = _missing_journal_links(
        journals=journals,
        known_order_ids=known_order_ids,
        known_execution_ids=known_execution_ids,
    )
    add(
        "journal_links",
        "pass" if not missing_journal_links else "fail",
        "Journal entries link only to known orders/executions."
        if not missing_journal_links
        else f"Journal entries reference missing ids: {', '.join(missing_journal_links)}.",
    )

    zero_cap = _decimal_value(zero_dte_runtime.get("max_premium_per_trade"))
    zero_policy_ok = (
        zero_dte_runtime.get("mode", mode) == "paper"
        and zero_cap == Decimal("150")
        and zero_dte_runtime.get("max_trades_per_day") == 1
        and isinstance(zero_dte_runtime.get("auto_execute_enabled"), bool)
    )
    add(
        "zero_dte_lottery_runtime_policy",
        "pass" if zero_policy_ok else "fail",
        "Zero-DTE lottery runtime is paper-only, capped at $150, limited to one trade per session, and exposes an explicit auto-order switch."
        if zero_policy_ok
        else "Zero-DTE lottery runtime does not prove the expected cap, daily guard, paper mode, or explicit auto-order switch.",
    )

    daily_lottery_overages = _zero_dte_daily_order_overages(
        orders=orders,
        max_trades_per_day=int(zero_dte_runtime.get("max_trades_per_day") or 1),
        mode=mode,
    )
    add(
        "zero_dte_lottery_daily_order_guard",
        "pass" if not daily_lottery_overages else "fail",
        "Recent zero-DTE lottery orders do not exceed the per-session cap."
        if not daily_lottery_overages
        else f"Zero-DTE lottery orders exceed the session cap on: {', '.join(daily_lottery_overages)}.",
    )

    add(
        "account_snapshot_available",
        "pass" if snapshot.get("account_snapshot") else "fail",
        "Latest account snapshot is available."
        if snapshot.get("account_snapshot")
        else "Latest account snapshot is missing.",
    )
    return checks


def summarize_snapshot(action: str, snapshot: dict[str, Any]) -> str:
    controls = snapshot.get("controls") or {}
    runtime = snapshot.get("runtime") or {}
    spreads = snapshot.get("spreads") or []
    open_spreads = [spread for spread in spreads if spread.get("status") in MONITORABLE_SPREAD_STATUSES]
    next_action = runtime.get("next_action") or "unknown"
    lottery_runtime = snapshot.get("zero_dte_lottery_runtime") or {}
    lottery_status = "on" if lottery_runtime.get("auto_execute_enabled") else "off"
    if action == "arm":
        return (
            "Unattended paper mode armed: new bull put entries are disabled, "
            f"{len(open_spreads)} monitorable spread(s) remain under scheduler supervision, "
            f"zero-DTE lottery auto-order is {lottery_status}."
        )
    if action == "resume":
        return (
            "Bull put auto-entry resumed: "
            f"next action is {next_action}, scheduler enabled={bool(controls.get('scheduler_enabled'))}, "
            f"zero-DTE lottery auto-order is {lottery_status}."
        )
    covered_summary = (snapshot.get("covered_call_activity") or {}).get("summary") or {}
    pending_lifecycle = len((snapshot.get("covered_call_activity") or {}).get("lifecycle_tasks") or [])
    return (
        f"Unattended paper status: next action is {next_action}; "
        f"{len(open_spreads)} monitorable bull put spread(s), "
        f"{pending_lifecycle} covered-call lifecycle task(s), "
        f"{covered_summary.get('executed_positions', 0)} open covered-call position(s), "
        f"zero-DTE lottery auto-order is {lottery_status}."
    )


def build_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    runtime = snapshot.get("runtime") or {}
    spreads = snapshot.get("spreads") or []
    orders = snapshot.get("orders") or []
    orders_by_id = {
        str(order.get("id")): order
        for order in orders
        if isinstance(order, dict) and order.get("id") is not None
    }
    executions = snapshot.get("executions") or []
    journals = snapshot.get("journals") or []
    covered_call_activity = snapshot.get("covered_call_activity") or {}
    operator_status = snapshot.get("operator_status") or {}
    audit_events = snapshot.get("audit_events") or []
    audit_summary = _snapshot_audit_summary(snapshot)
    broker_profiles = _snapshot_broker_profiles(snapshot)
    paper_mandate = _snapshot_paper_mandate(snapshot)
    return {
        "strategy_loop_checks": build_strategy_loop_checks(snapshot),
        "strategy_loop_summary": summarize_strategy_loop(snapshot),
        "health": snapshot.get("health"),
        "controls": snapshot.get("controls"),
        "operator_status": operator_status,
        "operator_posture_reason": operator_status.get("operator_posture_reason"),
        "operator_reason_codes": _operator_reason_codes(operator_status),
        "broker_profiles": broker_profiles,
        "paper_mandate": paper_mandate,
        "audit_events": audit_events[:20] if isinstance(audit_events, list) else [],
        "audit_summary": audit_summary,
        "runtime": runtime,
        "monitorable_spreads": [
            {
                "id": spread.get("id"),
                "symbol": spread.get("underlying_symbol"),
                "status": spread.get("status"),
                "expiration_date": spread.get("expiration_date"),
                "short_strike": spread.get("short_strike"),
                "long_strike": spread.get("long_strike"),
                "entry_net_credit": spread.get("entry_net_credit"),
                "last_synced_at": spread.get("last_synced_at"),
                "monitor": _bull_put_monitor_payload(spread),
                "lifecycle_warning": _bull_put_close_order_warning(spread, orders_by_id),
            }
            for spread in spreads
            if spread.get("status") in MONITORABLE_SPREAD_STATUSES
        ],
        "covered_call_summary": covered_call_activity.get("summary"),
        "covered_call_lifecycle_tasks": covered_call_activity.get("lifecycle_tasks") or [],
        "zero_dte_lottery_runtime": snapshot.get("zero_dte_lottery_runtime"),
        "latest_account_snapshot": summarize_account_snapshot(snapshot.get("account_snapshot")),
        "latest_pre_open_run": summarize_pre_open_run((snapshot.get("pre_open_runs") or [None])[0]),
        "recent_orders": [summarize_order(order) for order in orders[:10]],
        "recent_executions": [summarize_execution(execution) for execution in executions[:10]],
        "recent_journals": [summarize_journal(journal) for journal in journals[:10]],
    }


def summarize_strategy_loop(snapshot: dict[str, Any]) -> dict[str, Any]:
    checks = build_strategy_loop_checks(snapshot)
    spreads = snapshot.get("spreads") or []
    orders = snapshot.get("orders") or []
    executions = snapshot.get("executions") or []
    journals = snapshot.get("journals") or []
    covered_call_activity = snapshot.get("covered_call_activity") or {}
    operator_status = snapshot.get("operator_status") or {}
    audit_summary = _snapshot_audit_summary(snapshot)
    return {
        "account_id": snapshot.get("account_id"),
        "mode": snapshot.get("mode") or "paper",
        "operator_posture_status": operator_status.get("status"),
        "operator_posture_reason": operator_status.get("operator_posture_reason"),
        "operator_reason_codes": _operator_reason_codes(operator_status),
        "check_status": "passed" if all(check["status"] != "fail" for check in checks) else "failed",
        "failed_checks": [check["name"] for check in checks if check["status"] == "fail"],
        "warning_checks": [check["name"] for check in checks if check["status"] == "warn"],
        "monitorable_spread_count": sum(
            1 for spread in spreads if spread.get("status") in MONITORABLE_SPREAD_STATUSES
        ),
        "covered_call_lifecycle_task_count": len(covered_call_activity.get("lifecycle_tasks") or []),
        "recent_order_count": len(orders),
        "recent_execution_count": len(executions),
        "recent_journal_count": len(journals),
        "zero_dte_lottery_auto_order_enabled": bool(
            (snapshot.get("zero_dte_lottery_runtime") or {}).get("auto_execute_enabled")
        ),
        "broker_profile_count": len(_snapshot_broker_profiles(snapshot)),
        "audit_event_count": audit_summary.get("event_count") if isinstance(audit_summary, dict) else None,
        "audit_warning_count": audit_summary.get("warning_count") if isinstance(audit_summary, dict) else None,
    }


def summarize_account_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    return {
        "account_id": snapshot.get("account_id"),
        "currency": snapshot.get("currency"),
        "cash_balance": snapshot.get("cash_balance"),
        "net_liquidation": snapshot.get("net_liquidation"),
        "buying_power": snapshot.get("buying_power"),
        "captured_at": snapshot.get("captured_at"),
        "positions": [
            {
                "symbol": position.get("symbol"),
                "asset_type": position.get("asset_type"),
                "quantity": position.get("quantity"),
                "market_value": position.get("market_value"),
                "unrealized_pnl": position.get("unrealized_pnl"),
            }
            for position in snapshot.get("positions", [])
        ],
    }


def summarize_order(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order.get("id"),
        "external_order_id": order.get("external_order_id"),
        "symbol": order.get("symbol"),
        "asset_type": order.get("asset_type"),
        "side": order.get("side"),
        "quantity": order.get("quantity"),
        "order_type": order.get("order_type"),
        "status": order.get("status"),
        "limit_price": order.get("limit_price"),
        "submitted_at": order.get("submitted_at"),
        "updated_at": order.get("updated_at"),
    }


def summarize_execution(execution: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": execution.get("id"),
        "order_id": execution.get("order_id"),
        "external_execution_id": execution.get("external_execution_id"),
        "symbol": execution.get("symbol"),
        "side": execution.get("side"),
        "quantity": execution.get("quantity"),
        "price": execution.get("price"),
        "executed_at": execution.get("executed_at"),
    }


def summarize_journal(journal: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": journal.get("id"),
        "symbol": journal.get("symbol"),
        "entry_type": journal.get("entry_type"),
        "title": journal.get("title"),
        "order_id": journal.get("order_id"),
        "execution_id": journal.get("execution_id"),
        "created_at": journal.get("created_at"),
    }


def summarize_pre_open_run(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if run is None:
        return None
    assessment = run.get("assessment") or {}
    return {
        "id": run.get("id"),
        "target_session_date": run.get("target_session_date"),
        "review_status": run.get("review_status"),
        "review_summary": run.get("review_summary"),
        "last_reviewed_at": run.get("last_reviewed_at"),
        "assessment": {
            "analyzed_at": assessment.get("analyzed_at"),
            "session": assessment.get("session"),
            "freshness_status": assessment.get("freshness_status"),
            "regime": assessment.get("regime"),
            "trade_action": assessment.get("trade_action"),
            "summary": assessment.get("summary"),
        },
    }


def run_action(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.base_url.rstrip("/")
    with httpx.Client(base_url=base_url, timeout=args.timeout_seconds) as client:
        if args.action == "arm":
            snapshot = arm_unattended(
                client,
                account_id=args.account_id,
                mode=args.mode,
                zero_dte_lottery_auto_order=args.zero_dte_lottery_auto_order,
            )
        elif args.action == "resume":
            snapshot = resume_entries(
                client,
                account_id=args.account_id,
                mode=args.mode,
                zero_dte_lottery_auto_order=args.zero_dte_lottery_auto_order,
            )
        else:
            if args.zero_dte_lottery_auto_order != "leave":
                raise UnattendedPaperError("status does not mutate zero-DTE lottery auto-order; use arm or resume.")
            snapshot = collect_snapshot(client, account_id=args.account_id, mode=args.mode)
            validate_strategy_loop_snapshot(snapshot)

    report = build_report(
        script="run_unattended_paper.py",
        workflow=f"unattended-paper-{args.action}",
        status="passed",
        mode=args.mode,
        target=base_url,
        summary=summarize_snapshot(args.action, snapshot),
        payload=build_payload(snapshot),
    )
    attach_notification_result(report, args=args)
    return report


def _automation_control(controls: dict[str, Any], strategy_id: str) -> dict[str, Any] | None:
    for item in controls.get("automation_controls") or []:
        if isinstance(item, dict) and item.get("strategy_id") == strategy_id:
            return item
    return None


def _snapshot_broker_profiles(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = snapshot.get("broker_profiles")
    if isinstance(profiles, list) and profiles:
        return [profile for profile in profiles if isinstance(profile, dict)]
    operator_status = snapshot.get("operator_status") if isinstance(snapshot.get("operator_status"), dict) else {}
    profiles = operator_status.get("broker_profiles") if isinstance(operator_status, dict) else None
    if isinstance(profiles, list):
        return [profile for profile in profiles if isinstance(profile, dict)]
    return []


def _selected_broker_profile(
    *,
    broker_profiles: list[dict[str, Any]],
    account_id: str | None,
) -> dict[str, Any] | None:
    for profile in broker_profiles:
        if profile.get("external_account_id") in {None, account_id}:
            return profile
    return broker_profiles[0] if broker_profiles else None


def _snapshot_paper_mandate(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    operator_status = snapshot.get("operator_status") if isinstance(snapshot.get("operator_status"), dict) else {}
    mandate = operator_status.get("paper_mandate") if isinstance(operator_status, dict) else None
    if isinstance(mandate, dict):
        return mandate
    controls = snapshot.get("controls") if isinstance(snapshot.get("controls"), dict) else {}
    mandate = controls.get("paper_mandate") if isinstance(controls, dict) else None
    return mandate if isinstance(mandate, dict) else None


def _operator_reason_codes(operator_status: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    checks = operator_status.get("checks") if isinstance(operator_status, dict) else None
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict) and check.get("reason_code"):
                codes.append(str(check["reason_code"]))
    mandate = operator_status.get("paper_mandate") if isinstance(operator_status, dict) else None
    mandate_codes = mandate.get("reason_codes") if isinstance(mandate, dict) else None
    if isinstance(mandate_codes, list):
        codes.extend(str(code) for code in mandate_codes if code)
    return sorted(set(codes))


def _snapshot_audit_summary(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    audit_summary = snapshot.get("audit_summary")
    if isinstance(audit_summary, dict):
        return audit_summary
    operator_status = snapshot.get("operator_status") if isinstance(snapshot.get("operator_status"), dict) else {}
    audit_summary = operator_status.get("audit_summary") if isinstance(operator_status, dict) else None
    if isinstance(audit_summary, dict):
        return audit_summary
    audit_events = snapshot.get("audit_events")
    if isinstance(audit_events, list):
        warning_count = sum(
            1
            for event in audit_events
            if isinstance(event, dict) and event.get("warning_code")
        )
        return {"event_count": len(audit_events), "warning_count": warning_count}
    return None


def _missing_linked_orders(spreads: list[dict[str, Any]], known_order_ids: set[str]) -> list[str]:
    missing: set[str] = set()
    for spread in spreads:
        if not isinstance(spread, dict) or spread.get("status") not in MONITORABLE_SPREAD_STATUSES:
            continue
        for key in ("long_entry_order_id", "short_entry_order_id", "long_exit_order_id", "short_exit_order_id"):
            order_id = spread.get(key)
            if order_id is not None and str(order_id) not in known_order_ids:
                missing.add(str(order_id))
    return sorted(missing)


def _bull_put_close_order_warnings(
    spreads: list[dict[str, Any]],
    orders_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    warnings: list[str] = []
    for spread in spreads:
        warning = _bull_put_close_order_warning(spread, orders_by_id)
        if warning:
            warnings.append(str(spread.get("id") or warning["order_id"]))
    return sorted(warnings)


def _bull_put_close_order_warning(
    spread: dict[str, Any],
    orders_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(spread, dict) or spread.get("status") not in MONITORABLE_SPREAD_STATUSES:
        return None
    short_exit_order_id = spread.get("short_exit_order_id")
    short_exit_order = orders_by_id.get(str(short_exit_order_id))
    raw_payload = spread.get("raw_payload") if isinstance(spread.get("raw_payload"), dict) else None
    lifecycle = (raw_payload or {}).get("lifecycle") or {}
    return bull_put_close_order_warning(
        spread_status=spread.get("status"),
        short_exit_order_id=short_exit_order_id,
        short_exit_order_status=(short_exit_order or {}).get("status")
        or spread.get("latest_close_order_status")
        or lifecycle.get("close_order_state"),
        short_symbol=spread.get("short_symbol"),
        raw_payload=raw_payload,
        exit_reason=spread.get("exit_reason"),
        orders_by_id=orders_by_id,
        latest_monitor_should_close=spread.get("latest_monitor_should_close"),
        lifecycle_warning_code=spread.get("lifecycle_warning_code") or lifecycle.get("warning"),
        manual_action_required=spread.get("manual_action_required") or lifecycle.get("manual_action_required"),
    )


def _bull_put_monitor_payload(spread: dict[str, Any]) -> dict[str, Any] | None:
    raw_payload = spread.get("raw_payload") if isinstance(spread.get("raw_payload"), dict) else None
    raw_monitor = (raw_payload or {}).get("monitor")
    if isinstance(raw_monitor, dict):
        return raw_monitor
    monitor: dict[str, Any] = {}
    if "latest_monitor_should_close" in spread:
        monitor["should_close"] = spread.get("latest_monitor_should_close")
    if spread.get("next_monitor_after") is not None:
        monitor["next_monitor_after"] = spread.get("next_monitor_after")
    return monitor or None


def _missing_lifecycle_orders(tasks: list[dict[str, Any]], known_order_ids: set[str]) -> list[str]:
    missing: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for key in ("open_order_id", "close_order_id", "roll_buyback_order_id", "roll_sell_order_id"):
            order_id = task.get(key)
            if order_id is not None and str(order_id) not in known_order_ids:
                missing.add(str(order_id))
    return sorted(missing)


def _missing_journal_links(
    *,
    journals: list[dict[str, Any]],
    known_order_ids: set[str],
    known_execution_ids: set[str],
) -> list[str]:
    missing: set[str] = set()
    for journal in journals:
        if not isinstance(journal, dict):
            continue
        order_id = journal.get("order_id")
        if order_id is not None and str(order_id) not in known_order_ids:
            missing.add(f"order:{order_id}")
        execution_id = journal.get("execution_id")
        if execution_id is not None and str(execution_id) not in known_execution_ids:
            missing.add(f"execution:{execution_id}")
    return sorted(missing)


def _zero_dte_daily_order_overages(
    *,
    orders: list[dict[str, Any]],
    max_trades_per_day: int,
    mode: str,
) -> list[str]:
    by_session: dict[str, int] = {}
    for order in orders:
        if not _is_zero_dte_lottery_order(order, mode=mode):
            continue
        submitted_at = order.get("submitted_at")
        if not submitted_at:
            continue
        session_date = str(submitted_at)[:10]
        by_session[session_date] = by_session.get(session_date, 0) + 1
    return sorted(
        session_date
        for session_date, count in by_session.items()
        if count > max_trades_per_day
    )


def _is_zero_dte_lottery_order(order: dict[str, Any], *, mode: str) -> bool:
    if not isinstance(order, dict):
        return False
    if order.get("mode", mode) != mode:
        return False
    if order.get("asset_type") != "option" or order.get("side") != "buy":
        return False
    if order.get("status") in {"canceled", "rejected"}:
        return False
    payload = order.get("raw_payload")
    request_payload = payload.get("submission_request") if isinstance(payload, dict) else None
    remark = request_payload.get("remark") if isinstance(request_payload, dict) else None
    return isinstance(remark, str) and remark.startswith(ZERO_DTE_STRATEGY_ID)


def _decimal_value(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


NOTIFICATION_LEVEL_RANK = {
    "info": 0,
    "warning": 1,
    "critical": 2,
}


def attach_notification_result(report: dict[str, Any], *, args: argparse.Namespace) -> None:
    notification = build_unattended_notification(report, action=args.action)
    result = dispatch_unattended_notification(
        notification,
        channel=args.notification_channel,
        notification_file=args.notification_file,
        min_level=args.notification_min_level,
    )
    payload = report.setdefault("payload", {})
    if isinstance(payload, dict):
        payload["notification"] = result


def build_unattended_notification(report: dict[str, Any], *, action: str) -> dict[str, Any]:
    payload = report.get("payload") if isinstance(report.get("payload"), dict) else {}
    strategy_summary = payload.get("strategy_loop_summary") if isinstance(payload, dict) else {}
    if not isinstance(strategy_summary, dict):
        strategy_summary = {}
    failed_checks = list(strategy_summary.get("failed_checks") or [])
    warning_checks = list(strategy_summary.get("warning_checks") or [])
    status = report.get("status")
    if status == "failed" or failed_checks:
        level = "critical"
    elif warning_checks or strategy_summary.get("zero_dte_lottery_auto_order_enabled"):
        level = "warning"
    else:
        level = "info"

    return {
        "schema_version": "unattended_paper_notification_v1",
        "event_type": f"unattended_paper_{action}",
        "level": level,
        "title": report.get("summary") or f"Unattended paper {action} completed.",
        "generated_at": report.get("generated_at"),
        "status": status,
        "target": report.get("target"),
        "mode": report.get("mode"),
        "account_id": (
            strategy_summary.get("account_id")
            or (payload.get("runtime") or {}).get("external_account_id")
            or payload.get("account_id")
        ),
        "failed_checks": failed_checks,
        "warning_checks": warning_checks,
        "metrics": {
            "monitorable_spread_count": strategy_summary.get("monitorable_spread_count"),
            "covered_call_lifecycle_task_count": strategy_summary.get("covered_call_lifecycle_task_count"),
            "recent_order_count": strategy_summary.get("recent_order_count"),
            "recent_execution_count": strategy_summary.get("recent_execution_count"),
            "recent_journal_count": strategy_summary.get("recent_journal_count"),
            "zero_dte_lottery_auto_order_enabled": strategy_summary.get("zero_dte_lottery_auto_order_enabled"),
        },
        "reserved_external_channels": ["email", "push", "sms"],
    }


def dispatch_unattended_notification(
    notification: dict[str, Any],
    *,
    channel: str,
    notification_file: Path,
    min_level: str = "info",
) -> dict[str, Any]:
    level = str(notification.get("level") or "info")
    if NOTIFICATION_LEVEL_RANK[level] < NOTIFICATION_LEVEL_RANK[min_level]:
        return {
            "channel": channel,
            "emitted": False,
            "reason": f"Notification level {level} is below minimum {min_level}.",
            "payload": notification,
        }
    if channel == "none":
        return {
            "channel": channel,
            "emitted": False,
            "reason": "Notification channel disabled.",
            "payload": notification,
        }
    if channel == "dry-run":
        return {
            "channel": channel,
            "emitted": False,
            "reason": "Dry-run notification only; no external delivery attempted.",
            "payload": notification,
        }
    if channel == "console":
        print(json.dumps(notification, ensure_ascii=True), file=sys.stderr)
        return {
            "channel": channel,
            "emitted": True,
            "reason": "Notification written to stderr.",
            "payload": notification,
        }
    if channel == "file":
        notification_file.parent.mkdir(parents=True, exist_ok=True)
        with notification_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(notification, ensure_ascii=True))
            handle.write("\n")
        return {
            "channel": channel,
            "emitted": True,
            "reason": f"Notification appended to {notification_file}.",
            "payload": notification,
        }
    raise UnattendedPaperError(f"Notification channel '{channel}' is not supported.")


def main() -> None:
    args = parse_args()
    try:
        report = run_action(args)
    except Exception as error:
        report = build_report(
            script="run_unattended_paper.py",
            workflow=f"unattended-paper-{args.action}",
            status="failed",
            mode=args.mode,
            target=args.base_url.rstrip("/"),
            summary="Unattended paper workflow failed.",
            error=str(error),
            payload={"account_id": args.account_id},
        )
        attach_notification_result(report, args=args)
        emit_report(report, json_output=str(args.json_output) if args.json_output else None)
        raise SystemExit(1)
    emit_report(report, json_output=str(args.json_output) if args.json_output else None)


if __name__ == "__main__":
    main()
