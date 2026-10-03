from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from stocks_tool.domain.strategies.bull_put import BullPutRules, bull_put_exit_reason
from stocks_tool.domain.strategies.common import days_to_expiration as shared_days_to_expiration
from stocks_tool.domain.models import BullPutSpread, OptionMarketSnapshot


def estimated_exit_debit(
    *,
    short_leg: OptionMarketSnapshot,
    long_leg: OptionMarketSnapshot,
) -> Decimal | None:
    if short_leg.ask is None or long_leg.bid is None:
        return None
    return short_leg.ask - long_leg.bid


def estimated_pnl(
    *,
    spread: BullPutSpread,
    estimated_exit_debit: Decimal | None,
) -> Decimal | None:
    if spread.entry_net_credit is None or estimated_exit_debit is None:
        return None
    return (spread.entry_net_credit - estimated_exit_debit) * Decimal(spread.contracts) * Decimal("100")


def determine_exit_reason(
    *,
    spread: BullPutSpread,
    underlying_price: Decimal,
    estimated_exit_debit: Decimal | None,
    days_to_expiration: int,
    close_days_to_expiration: int,
    stop_loss_exit_multiple: Decimal,
    take_profit_exit_ratio: Decimal,
) -> str | None:
    return bull_put_exit_reason(
        underlying_price=underlying_price,
        short_strike=spread.short_strike,
        estimated_exit_debit=estimated_exit_debit,
        entry_credit=spread.entry_net_credit,
        days_to_expiration=days_to_expiration,
        rules=BullPutRules(
            close_days_to_expiration=close_days_to_expiration,
            stop_loss_exit_multiple=stop_loss_exit_multiple,
            take_profit_exit_ratio=take_profit_exit_ratio,
            require_trend=False,
        ),
    )


def days_to_expiration(
    *,
    expiry_date: date,
    scanned_at: datetime,
    market_timezone: ZoneInfo,
) -> int:
    return shared_days_to_expiration(
        expiry_date,
        scanned_at,
        market_timezone=market_timezone,
    )
