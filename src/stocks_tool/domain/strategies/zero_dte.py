"""Pure Zero-DTE research candidate and lifecycle rules.

The selector is deliberately useful for research only.  Nothing in this
module authorizes a broker order; the application service keeps the existing
execution lock in place.
"""

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
    option_quote_liquidity_reasons,
    right_name,
    value,
)


@dataclass(frozen=True)
class ZeroDteRules:
    max_premium_per_trade: Decimal = Decimal("150")
    contracts_per_trade: int = 1
    delta_target: Decimal = Decimal("0.22")
    delta_min: Decimal = Decimal("0.15")
    delta_max: Decimal = Decimal("0.30")
    min_open_interest: int = 100
    min_volume: int = 10
    min_bid: Decimal = Decimal("0.05")
    max_bid_ask_spread_pct: Decimal = Decimal("0.20")
    max_option_quote_age_seconds: int = 1800

    @classmethod
    def from_settings(cls, settings: Any) -> "ZeroDteRules":
        return cls(**{field: getattr(settings, field) for field in cls.__dataclass_fields__ if hasattr(settings, field)})


@dataclass(frozen=True)
class ZeroDteSelection:
    symbol: str
    direction: str
    expiration: date
    days_to_expiration: int
    quote: Any
    contracts: int
    premium_at_ask: Decimal


def select_zero_dte_candidate(
    *,
    symbol: str,
    direction: str,
    underlying_price: Decimal,
    evaluated_at: datetime,
    quotes: Iterable[Any],
    rules: ZeroDteRules,
) -> ZeroDteSelection | None:
    requested = direction.lower().strip()
    if requested not in {"call", "put"}:
        return None
    today = evaluated_at.astimezone(MARKET_TIMEZONE).date()
    spot = decimal(underlying_price, Decimal("0")) or Decimal("0")
    candidates = []
    for quote in quotes:
        expiration = value(quote, "expiration_date", value(quote, "expiration"))
        strike = decimal(value(quote, "strike"))
        bid = decimal(value(quote, "bid"))
        ask = decimal(value(quote, "ask"))
        delta = decimal(value(quote, "delta"))
        if (
            right_name(quote) != requested
            or expiration is None
            or str(expiration) != today.isoformat()
            or strike is None
            or (requested == "call" and strike < spot)
            or (requested == "put" and strike > spot)
            or delta is None or not rules.delta_min <= abs(delta) <= rules.delta_max
            or bid is None or ask is None or bid < rules.min_bid or ask <= bid
            or integer(value(quote, "open_interest"), 0) < rules.min_open_interest
            or integer(value(quote, "volume"), 0) < rules.min_volume
        ):
            continue
        if option_quote_liquidity_reasons(
            quote,
            evaluated_at=evaluated_at,
            max_bid_ask_spread_pct=rules.max_bid_ask_spread_pct,
            min_volume=rules.min_volume,
            min_open_interest=rules.min_open_interest,
            max_age_seconds=rules.max_option_quote_age_seconds,
            label="Zero-DTE option",
        ):
            continue
        premium = ask * Decimal(str(value(quote, "contract_multiplier", 100))) * Decimal(rules.contracts_per_trade)
        if premium > rules.max_premium_per_trade:
            continue
        candidates.append((quote, premium))
    if not candidates:
        return None
    quote, premium = min(
        candidates,
        key=lambda pair: (
            abs(abs(decimal(value(pair[0], "delta"), Decimal("0")) or Decimal("0")) - rules.delta_target),
            pair[1],
            abs((decimal(value(pair[0], "strike"), spot) or spot) - spot),
        ),
    )
    return ZeroDteSelection(
        symbol=symbol.upper(),
        direction=requested,
        expiration=today,
        days_to_expiration=days_to_expiration(today, evaluated_at),
        quote=quote,
        contracts=rules.contracts_per_trade,
        premium_at_ask=premium.quantize(Decimal("0.01")),
    )
