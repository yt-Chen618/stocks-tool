from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

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
    if days_to_expiration <= close_days_to_expiration:
        return "days_to_expiration_limit"
    if underlying_price <= spread.short_strike:
        return "short_strike_breach"
    if spread.entry_net_credit is None or estimated_exit_debit is None:
        return None
    if estimated_exit_debit >= (spread.entry_net_credit * stop_loss_exit_multiple):
        return "stop_loss"
    if estimated_exit_debit <= (spread.entry_net_credit * take_profit_exit_ratio):
        return "take_profit"
    return None


def days_to_expiration(
    *,
    expiry_date: date,
    scanned_at: datetime,
    market_timezone: ZoneInfo,
) -> int:
    scanned_date = scanned_at.astimezone(market_timezone).date()
    return (expiry_date - scanned_date).days
