"""Pure bull-put candidate rules used by online preview and research fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

from stocks_tool.domain.strategies.common import (
    MARKET_TIMEZONE,
    decimal,
    days_to_expiration,
    integer,
    moving_average,
    option_quote_liquidity_reasons,
    right_name,
    select_nearest_expiration,
    value,
)


@dataclass(frozen=True)
class BullPutRules:
    min_dte: int = 28
    max_dte: int = 35
    short_delta_target: Decimal = Decimal("0.22")
    short_delta_min: Decimal = Decimal("0.18")
    short_delta_max: Decimal = Decimal("0.28")
    min_open_interest: int = 200
    min_short_leg_volume: int = 10
    min_long_leg_volume: int = 10
    max_option_quote_age_seconds: int = 15
    max_bid_ask_spread_pct: Decimal = Decimal("0.10")
    min_credit_per_width_ratio: Decimal = Decimal("0.18")
    min_conservative_credit_per_width_ratio: Decimal = Decimal("0.10")
    min_mid_credit: Decimal = Decimal("0.20")
    per_trade_max_account_risk_pct: Decimal = Decimal("0.01")
    architecture_max_account_risk_pct: Decimal = Decimal("0.02")
    account_max_open_spreads: int = 2
    per_symbol_max_open_spreads: int = 1
    correlated_group_max_open_spreads: int = 1
    max_new_spreads_per_day: int = 1
    contracts_per_trade: int = 1
    take_profit_exit_ratio: Decimal = Decimal("0.50")
    stop_loss_exit_multiple: Decimal = Decimal("2.00")
    close_days_to_expiration: int = 7
    require_trend: bool = True

    @classmethod
    def from_settings(cls, settings: Any) -> "BullPutRules":
        return cls(**{field: getattr(settings, field) for field in cls.__dataclass_fields__ if hasattr(settings, field)})


@dataclass(frozen=True)
class BullPutSelection:
    symbol: str
    expiration: date
    days_to_expiration: int
    width: Decimal
    short_put: Any
    long_put: Any
    short_mid: Decimal
    long_mid: Decimal
    mid_credit: Decimal
    conservative_credit: Decimal
    reasons: tuple[str, ...] = ()


def width_for_underlying_price(underlying_price: Decimal) -> Decimal:
    """The paper strategy's configured width ladder.

    This is intentionally the same ladder exposed by
    ``BullPutSpreadStrategySettings.width_for_underlying_price``.
    """

    if underlying_price < Decimal("75"):
        return Decimal("1")
    if underlying_price < Decimal("250"):
        return Decimal("2")
    return Decimal("3")


def bull_put_trend_reasons(
    *,
    underlying: Any,
    bars: Iterable[Any],
    require_trend: bool = True,
) -> list[str]:
    if not require_trend:
        return []
    closes = [decimal(value(bar, "close")) for bar in bars]
    closes = [item for item in closes if item is not None]
    if len(closes) < 50:
        return ["At least 50 daily bars are required for trend filtering."]
    sma20 = moving_average(closes[-20:])
    sma50 = moving_average(closes[-50:])
    last = decimal(value(underlying, "last_done"), Decimal("0")) or Decimal("0")
    previous = decimal(value(underlying, "prev_close"), Decimal("0")) or Decimal("0")
    opening = decimal(value(underlying, "open"), Decimal("0")) or Decimal("0")
    reasons: list[str] = []
    if sma20 is None or sma50 is None:
        return ["Daily bars do not contain enough close values for trend filtering."]
    if last <= sma20:
        reasons.append("Underlying price is below the 20-day moving average.")
    if sma20 <= sma50:
        reasons.append("20-day moving average is not above the 50-day moving average.")
    if previous > 0 and last < previous * Decimal("0.995"):
        reasons.append("Underlying price is trading more than 0.5% below the previous close.")
    if previous > 0 and opening < previous * Decimal("0.98"):
        reasons.append("Underlying opened more than 2% below the previous close.")
    return reasons


def is_short_put_candidate(quote: Any, *, rules: BullPutRules) -> bool:
    if right_name(quote) != "put":
        return False
    delta = decimal(value(quote, "delta"))
    return (
        delta is not None
        and rules.short_delta_min <= abs(delta) <= rules.short_delta_max
        and integer(value(quote, "open_interest"), 0) >= rules.min_open_interest
    )


def select_bull_put_candidate(
    *,
    symbol: str,
    underlying_price: Decimal,
    expiration_dates: Iterable[date | str] | None,
    quotes: Iterable[Any],
    evaluated_at: datetime,
    rules: BullPutRules,
    bars: Iterable[Any] | None = None,
    underlying: Any | None = None,
    enforce_trend: bool | None = None,
) -> BullPutSelection | None:
    """Select the same candidate gates as the paper preview.

    Quotes are selected by the actual configured DTE, delta, OI, volume,
    top-of-book, width, and credit rules.  A missing input returns no
    candidate; this function never manufactures a strike from spot.
    """

    underlying_price = decimal(underlying_price, Decimal("0")) or Decimal("0")
    if underlying_price <= 0:
        return None
    if enforce_trend if enforce_trend is not None else rules.require_trend:
        trend_reasons = bull_put_trend_reasons(
            underlying=underlying or {"last_done": underlying_price, "prev_close": underlying_price, "open": underlying_price},
            bars=bars or (),
            require_trend=True,
        )
        if trend_reasons:
            return None
    expiration = select_nearest_expiration(
        expiration_dates or (), evaluated_at,
        min_dte=rules.min_dte,
        max_dte=rules.max_dte,
    )
    if expiration is None:
        return None
    expiration_quotes = [
        quote for quote in quotes
        if right_name(quote) == "put"
        and value(quote, "expiration_date", value(quote, "expiration")) is not None
        and str(value(quote, "expiration_date", value(quote, "expiration"))) == expiration.isoformat()
    ]
    if not expiration_quotes:
        return None
    width = width_for_underlying_price(underlying_price)
    ranked = sorted(
        (quote for quote in expiration_quotes if is_short_put_candidate(quote, rules=rules)),
        key=lambda quote: (
            abs(abs(decimal(value(quote, "delta"), Decimal("0")) or Decimal("0")) - rules.short_delta_target),
            -integer(value(quote, "open_interest"), 0),
            -(decimal(value(quote, "strike"), Decimal("0")) or Decimal("0")),
        ),
    )
    for short_put in ranked:
        short_reasons = option_quote_liquidity_reasons(
            short_put,
            evaluated_at=evaluated_at,
            max_bid_ask_spread_pct=rules.max_bid_ask_spread_pct,
            min_volume=rules.min_short_leg_volume,
            min_open_interest=rules.min_open_interest,
            max_age_seconds=rules.max_option_quote_age_seconds,
            label="Short put",
        )
        if short_reasons:
            continue
        short_strike = decimal(value(short_put, "strike"))
        if short_strike is None:
            continue
        long_put = next(
            (
                quote for quote in expiration_quotes
                if decimal(value(quote, "strike")) == short_strike - width
                and right_name(quote) == "put"
            ),
            None,
        )
        if long_put is None:
            continue
        long_reasons = option_quote_liquidity_reasons(
            long_put,
            evaluated_at=evaluated_at,
            max_bid_ask_spread_pct=rules.max_bid_ask_spread_pct,
            min_volume=rules.min_long_leg_volume,
            min_open_interest=None,
            max_age_seconds=rules.max_option_quote_age_seconds,
            label="Long put",
        )
        if long_reasons:
            continue
        short_mid = _mid(short_put)
        long_mid = _mid(long_put)
        short_bid = decimal(value(short_put, "bid"))
        long_ask = decimal(value(long_put, "ask"))
        if short_mid is None or long_mid is None or short_bid is None or long_ask is None:
            continue
        mid_credit = short_mid - long_mid
        conservative_credit = short_bid - long_ask
        if (
            mid_credit < width * rules.min_credit_per_width_ratio
            or conservative_credit < width * rules.min_conservative_credit_per_width_ratio
            or mid_credit < rules.min_mid_credit
        ):
            continue
        return BullPutSelection(
            symbol=symbol.upper(),
            expiration=expiration,
            days_to_expiration=days_to_expiration(expiration, evaluated_at),
            width=width,
            short_put=short_put,
            long_put=long_put,
            short_mid=short_mid,
            long_mid=long_mid,
            mid_credit=mid_credit,
            conservative_credit=conservative_credit,
        )
    return None


def bull_put_cap_reasons(
    *,
    event: Any,
    width: Decimal,
    credit: Decimal,
    rules: BullPutRules,
) -> list[str]:
    """Apply the persisted strategy/runtime capacity gates when supplied.

    Backtest events may omit account state; omitted evidence remains unknown
    rather than being treated as a free capacity.  Existing broker previews
    continue to use their account and runtime services for the authoritative
    live check.
    """

    reasons: list[str] = []
    active_account = value(event, "active_account_spreads")
    active_symbol = value(event, "active_symbol_spreads")
    active_correlated = value(event, "active_correlated_spreads")
    entries_today = value(event, "entries_today")
    if active_account is not None and integer(active_account, 0) >= rules.account_max_open_spreads:
        reasons.append("account_open_spread_cap_reached")
    if active_symbol is not None and integer(active_symbol, 0) >= rules.per_symbol_max_open_spreads:
        reasons.append("symbol_open_spread_cap_reached")
    if active_correlated is not None and integer(active_correlated, 0) >= rules.correlated_group_max_open_spreads:
        reasons.append("correlated_open_spread_cap_reached")
    if entries_today is not None and integer(entries_today, 0) >= rules.max_new_spreads_per_day:
        reasons.append("daily_entry_cap_reached")
    nav = decimal(value(event, "net_liquidation", value(event, "account_net_liquidation")))
    if nav is not None and nav > 0:
        max_loss = width * Decimal(str(rules.contracts_per_trade)) * Decimal("100") - credit * Decimal(str(rules.contracts_per_trade)) * Decimal("100")
        if max_loss > nav * rules.per_trade_max_account_risk_pct:
            reasons.append("per_trade_risk_cap_reached")
        if max_loss > nav * rules.architecture_max_account_risk_pct:
            reasons.append("architecture_risk_cap_reached")
    return reasons


def bull_put_exit_reason(
    *,
    underlying_price: Decimal,
    short_strike: Decimal,
    estimated_exit_debit: Decimal | None,
    entry_credit: Decimal | None,
    days_to_expiration: int,
    rules: BullPutRules,
) -> str | None:
    """Use the production monitor's ordered close triggers."""

    if days_to_expiration <= rules.close_days_to_expiration:
        return "days_to_expiration_limit"
    if underlying_price <= short_strike:
        return "short_strike_breach"
    if entry_credit is None or estimated_exit_debit is None:
        return None
    if estimated_exit_debit >= entry_credit * rules.stop_loss_exit_multiple:
        return "stop_loss"
    if estimated_exit_debit <= entry_credit * rules.take_profit_exit_ratio:
        return "take_profit"
    return None


def _mid(quote: Any) -> Decimal | None:
    bid = decimal(value(quote, "bid"))
    ask = decimal(value(quote, "ask"))
    if bid is None or ask is None:
        return None
    return (bid + ask) / Decimal("2")
