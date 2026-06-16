from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from stocks_tool.application.services.bull_put.monitor import (
    days_to_expiration,
    determine_exit_reason,
    estimated_exit_debit,
    estimated_pnl,
)
from stocks_tool.domain.enums import BrokerName, ExecutionMode, OptionRight, SpreadStatus
from stocks_tool.domain.models import BullPutSpread, OptionMarketSnapshot


NOW = datetime(2026, 6, 15, 14, 45, tzinfo=timezone.utc)


def _spread(**updates) -> BullPutSpread:
    base = BullPutSpread(
        id="spread-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="QQQ.US",
        expiration_date=date(2026, 6, 26),
        contracts=1,
        width=Decimal("3"),
        long_symbol="QQQ260626P705000.US",
        long_strike=Decimal("705"),
        short_symbol="QQQ260626P708000.US",
        short_strike=Decimal("708"),
        status=SpreadStatus.OPEN,
        entry_net_credit=Decimal("0.52"),
    )
    return base.model_copy(update=updates)


def _option(symbol: str, *, bid: Decimal | None = None, ask: Decimal | None = None) -> OptionMarketSnapshot:
    return OptionMarketSnapshot(
        symbol=symbol,
        underlying_symbol="QQQ.US",
        expiration_date=date(2026, 6, 26),
        strike=Decimal("708"),
        right=OptionRight.PUT,
        last_done=Decimal("1.00"),
        prev_close=Decimal("1.05"),
        open=Decimal("1.02"),
        high=Decimal("1.10"),
        low=Decimal("0.95"),
        timestamp=NOW,
        volume=100,
        turnover=Decimal("10000"),
        bid=bid,
        ask=ask,
    )


def test_estimated_exit_debit_uses_short_ask_minus_long_bid() -> None:
    assert estimated_exit_debit(
        short_leg=_option("QQQ260626P708000.US", ask=Decimal("0.50")),
        long_leg=_option("QQQ260626P705000.US", bid=Decimal("0.13")),
    ) == Decimal("0.37")


def test_estimated_pnl_uses_contract_multiplier() -> None:
    assert estimated_pnl(spread=_spread(), estimated_exit_debit=Decimal("0.37")) == Decimal("15.00")


def test_determine_exit_reason_prioritizes_expiration_and_strike_risk() -> None:
    assert determine_exit_reason(
        spread=_spread(),
        underlying_price=Decimal("740"),
        estimated_exit_debit=Decimal("0.37"),
        days_to_expiration=7,
        close_days_to_expiration=7,
        stop_loss_exit_multiple=Decimal("2"),
        take_profit_exit_ratio=Decimal("0.5"),
    ) == "days_to_expiration_limit"

    assert determine_exit_reason(
        spread=_spread(),
        underlying_price=Decimal("707.99"),
        estimated_exit_debit=Decimal("0.37"),
        days_to_expiration=8,
        close_days_to_expiration=7,
        stop_loss_exit_multiple=Decimal("2"),
        take_profit_exit_ratio=Decimal("0.5"),
    ) == "short_strike_breach"


def test_determine_exit_reason_detects_stop_loss_and_take_profit() -> None:
    assert determine_exit_reason(
        spread=_spread(),
        underlying_price=Decimal("740"),
        estimated_exit_debit=Decimal("1.04"),
        days_to_expiration=8,
        close_days_to_expiration=7,
        stop_loss_exit_multiple=Decimal("2"),
        take_profit_exit_ratio=Decimal("0.5"),
    ) == "stop_loss"

    assert determine_exit_reason(
        spread=_spread(),
        underlying_price=Decimal("740"),
        estimated_exit_debit=Decimal("0.26"),
        days_to_expiration=8,
        close_days_to_expiration=7,
        stop_loss_exit_multiple=Decimal("2"),
        take_profit_exit_ratio=Decimal("0.5"),
    ) == "take_profit"


def test_days_to_expiration_uses_market_timezone_date() -> None:
    assert days_to_expiration(
        expiry_date=date(2026, 6, 26),
        scanned_at=datetime(2026, 6, 15, 23, 30, tzinfo=timezone.utc),
        market_timezone=ZoneInfo("America/New_York"),
    ) == 11
