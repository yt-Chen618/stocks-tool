from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from stocks_tool.domain.enums import SpreadStatus
from stocks_tool.domain.models import BullPutSpread, BullPutStrategyRuntimeState


def runtime_account_entry_block_reason(
    *,
    state: BullPutStrategyRuntimeState,
    max_new_spreads_per_day: int,
    daily_realized_loss_limit: Decimal,
) -> str | None:
    if not state.auto_entry_enabled:
        return "Automatic bull put entry is disabled for this account."
    if state.manual_pause:
        return "Bull put strategy is manually paused for this account."
    if state.kill_switch_active:
        return "Bull put kill switch is active for this account."
    if state.daily_entry_count >= max_new_spreads_per_day:
        return "Bull put daily entry cap has already been reached for this account."
    if state.daily_realized_pnl <= (daily_realized_loss_limit * Decimal("-1")):
        return "Bull put daily realized loss limit has already been reached for this account."
    return None


def runtime_entry_block_reason(
    *,
    state: BullPutStrategyRuntimeState,
    symbol: str,
    max_new_spreads_per_day: int,
    daily_realized_loss_limit: Decimal,
) -> str | None:
    account_reason = runtime_account_entry_block_reason(
        state=state,
        max_new_spreads_per_day=max_new_spreads_per_day,
        daily_realized_loss_limit=daily_realized_loss_limit,
    )
    if account_reason is not None:
        return account_reason
    if symbol in state.paused_symbols:
        return f"Bull put strategy is paused for '{symbol}'."
    return None


def runtime_next_action(
    *,
    state: BullPutStrategyRuntimeState,
    active_spread_count: int,
    max_new_spreads_per_day: int,
    entry_block_reason: str | None,
) -> str:
    if state.kill_switch_active or state.manual_pause or not state.auto_entry_enabled:
        return "resolve_runtime_controls"
    if active_spread_count:
        return "monitor_open_spread"
    if state.daily_entry_count >= max_new_spreads_per_day:
        return "wait_next_session"
    if entry_block_reason is not None:
        return "entry_blocked"
    return "scan_for_entry"


def next_monitor_after(
    *,
    active_spreads: list[BullPutSpread],
    monitor_interval_seconds: int,
    as_of: datetime,
) -> datetime | None:
    monitor_times: list[datetime] = []
    for spread in active_spreads:
        monitor_payload = (spread.raw_payload or {}).get("monitor") or {}
        next_monitor_at = monitor_payload.get("next_monitor_after")
        if isinstance(next_monitor_at, str):
            try:
                monitor_times.append(datetime.fromisoformat(next_monitor_at.replace("Z", "+00:00")))
                continue
            except ValueError:
                pass
        if spread.last_synced_at is not None:
            monitor_times.append(spread.last_synced_at + timedelta(seconds=monitor_interval_seconds))
    if monitor_times:
        return min(monitor_times).astimezone(timezone.utc)
    if active_spreads:
        return as_of + timedelta(seconds=monitor_interval_seconds)
    return None


def open_spread_count(active_spreads: list[BullPutSpread]) -> int:
    return sum(1 for spread in active_spreads if spread.status == SpreadStatus.OPEN)
