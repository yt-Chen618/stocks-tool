"""Pure covered-call candidate selection and risk calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

from stocks_tool.domain.strategies.common import (
    decimal,
    days_to_expiration,
    integer,
    option_quote_liquidity_reasons,
    right_name,
    select_nearest_expiration,
    value,
)


@dataclass(frozen=True)
class CoveredCallRules:
    min_shares: int = 100
    min_dte: int = 21
    max_dte: int = 45
    delta_target: Decimal = Decimal("0.30")
    delta_min: Decimal = Decimal("0.20")
    delta_max: Decimal = Decimal("0.35")
    min_otm_pct: Decimal = Decimal("0.02")
    max_otm_pct: Decimal = Decimal("0.12")
    min_open_interest: int = 100
    min_volume: int = 1
    min_bid: Decimal = Decimal("0.10")
    max_bid_ask_spread_pct: Decimal = Decimal("0.15")
    max_option_quote_age_seconds: int = 1800
    max_contracts_per_symbol: int = 1

    @classmethod
    def from_settings(cls, settings: Any) -> "CoveredCallRules":
        return cls(**{field: getattr(settings, field) for field in cls.__dataclass_fields__ if hasattr(settings, field)})


@dataclass(frozen=True)
class CoveredCallSelection:
    symbol: str
    expiration: date
    days_to_expiration: int
    quote: Any
    contracts: int
    covered_shares: int


def is_covered_call_quote_candidate(
    quote: Any,
    *,
    underlying_price: Decimal,
    expiration: date,
    evaluated_at: datetime,
    rules: CoveredCallRules,
    check_liquidity: bool = True,
) -> bool:
    """Apply the preview's non-liquidity call filters to one quote."""

    strike = decimal(value(quote, "strike"))
    delta = decimal(value(quote, "delta"))
    bid = decimal(value(quote, "bid"))
    spot = decimal(underlying_price, Decimal("0")) or Decimal("0")
    if (
        right_name(quote) != "call"
        or str(value(quote, "expiration_date", value(quote, "expiration"))) != expiration.isoformat()
        or strike is None
        or not spot * (Decimal("1") + rules.min_otm_pct) <= strike <= spot * (Decimal("1") + rules.max_otm_pct)
        or delta is None
        or not rules.delta_min <= delta <= rules.delta_max
        or integer(value(quote, "open_interest"), 0) < rules.min_open_interest
        or integer(value(quote, "volume"), 0) < rules.min_volume
        or bid is None
        or bid < rules.min_bid
    ):
        return False
    if not check_liquidity:
        return True
    return not option_quote_liquidity_reasons(
        quote,
        evaluated_at=evaluated_at,
        max_bid_ask_spread_pct=rules.max_bid_ask_spread_pct,
        min_volume=rules.min_volume,
        min_open_interest=rules.min_open_interest,
        max_age_seconds=rules.max_option_quote_age_seconds,
        label="Covered call",
    )


def select_covered_call_candidate(
    *,
    symbol: str,
    underlying_price: Decimal,
    shares: int | Decimal,
    expiration_dates: Iterable[date | str] | None,
    quotes: Iterable[Any],
    evaluated_at: datetime,
    rules: CoveredCallRules,
) -> CoveredCallSelection | None:
    shares_int = integer(shares, 0)
    if shares_int < rules.min_shares or decimal(underlying_price, Decimal("0")) <= 0:
        return None
    expiration = select_nearest_expiration(
        expiration_dates or (), evaluated_at,
        min_dte=rules.min_dte,
        max_dte=rules.max_dte,
    )
    if expiration is None:
        return None
    spot = decimal(underlying_price, Decimal("0")) or Decimal("0")
    ranked = []
    for quote in quotes:
        if not is_covered_call_quote_candidate(
            quote,
            underlying_price=spot,
            expiration=expiration,
            evaluated_at=evaluated_at,
            rules=rules,
        ):
            continue
        ranked.append(quote)
    ranked.sort(key=lambda quote: (
        abs((decimal(value(quote, "delta"), Decimal("0")) or Decimal("0")) - rules.delta_target),
        abs((decimal(value(quote, "strike"), spot) or spot) - spot),
        -integer(value(quote, "open_interest"), 0),
        -integer(value(quote, "volume"), 0),
    ))
    for quote in ranked[:12]:
        contracts = min(shares_int // 100, rules.max_contracts_per_symbol)
        if contracts <= 0:
            return None
        return CoveredCallSelection(
            symbol=symbol.upper(),
            expiration=expiration,
            days_to_expiration=days_to_expiration(expiration, evaluated_at),
            quote=quote,
            contracts=contracts,
            covered_shares=contracts * 100,
        )
    return None
