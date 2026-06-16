from datetime import date, datetime, timezone
from decimal import Decimal

from stocks_tool.application.services.bull_put.runtime import (
    next_monitor_after,
    runtime_account_entry_block_reason,
    runtime_entry_block_reason,
    runtime_next_action,
)
from stocks_tool.domain.enums import BrokerName, ExecutionMode, SpreadStatus
from stocks_tool.domain.models import BullPutSpread, BullPutStrategyRuntimeState


def _runtime_state(**updates) -> BullPutStrategyRuntimeState:
    base = BullPutStrategyRuntimeState(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        daily_entry_count=0,
        daily_realized_pnl=Decimal("0"),
    )
    return base.model_copy(update=updates)


def _spread(**updates) -> BullPutSpread:
    base = BullPutSpread(
        id="spread-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="QQQ.US",
        expiration_date=date(2026, 6, 19),
        contracts=1,
        width=Decimal("2"),
        long_symbol="QQQ260619P448000.US",
        long_strike=Decimal("448"),
        short_symbol="QQQ260619P450000.US",
        short_strike=Decimal("450"),
        status=SpreadStatus.OPEN,
    )
    return base.model_copy(update=updates)


def test_runtime_account_entry_block_reason_prioritizes_controls() -> None:
    reason = runtime_account_entry_block_reason(
        state=_runtime_state(auto_entry_enabled=False),
        max_new_spreads_per_day=1,
        daily_realized_loss_limit=Decimal("250"),
    )

    assert reason == "Automatic bull put entry is disabled for this account."


def test_runtime_entry_block_reason_checks_paused_symbol_after_account_controls() -> None:
    reason = runtime_entry_block_reason(
        state=_runtime_state(paused_symbols=["QQQ.US"]),
        symbol="QQQ.US",
        max_new_spreads_per_day=1,
        daily_realized_loss_limit=Decimal("250"),
    )

    assert reason == "Bull put strategy is paused for 'QQQ.US'."


def test_runtime_next_action_prefers_monitoring_active_spreads() -> None:
    action = runtime_next_action(
        state=_runtime_state(),
        active_spread_count=1,
        max_new_spreads_per_day=1,
        entry_block_reason=None,
    )

    assert action == "monitor_open_spread"


def test_next_monitor_after_prefers_payload_timestamp() -> None:
    as_of = datetime(2026, 6, 15, 14, 30, tzinfo=timezone.utc)
    spread = _spread(
        raw_payload={"monitor": {"next_monitor_after": "2026-06-15T15:00:00Z"}},
        last_synced_at=datetime(2026, 6, 15, 14, 10, tzinfo=timezone.utc),
    )

    result = next_monitor_after(
        active_spreads=[spread],
        monitor_interval_seconds=900,
        as_of=as_of,
    )

    assert result == datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc)
