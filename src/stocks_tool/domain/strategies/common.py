"""Small, dependency-free market and option predicates.

Values may be ordinary dictionaries (the fixture format) or the existing
Pydantic broker snapshots.  The adapters intentionally share these predicates
instead of copying threshold logic into a simulator.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable
from zoneinfo import ZoneInfo

MARKET_TIMEZONE = ZoneInfo("America/New_York")


def value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def decimal(value_: Any, default: Decimal | None = None) -> Decimal | None:
    if value_ is None or value_ == "":
        return default
    try:
        return Decimal(str(value_))
    except (TypeError, ValueError, ArithmeticError):
        return default


def integer(value_: Any, default: int = 0) -> int:
    try:
        return int(value_)
    except (TypeError, ValueError):
        return default


def parse_datetime(value_: Any) -> datetime:
    if isinstance(value_, datetime):
        parsed = value_
    else:
        parsed = datetime.fromisoformat(str(value_).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def parse_date(value_: Any) -> date:
    if isinstance(value_, datetime):
        return value_.date()
    if isinstance(value_, date):
        return value_
    return date.fromisoformat(str(value_))


def normalize_as_of(as_of: datetime) -> datetime:
    return as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=timezone.utc)


def market_date(as_of: datetime, *, market_timezone: ZoneInfo = MARKET_TIMEZONE) -> date:
    return normalize_as_of(as_of).astimezone(market_timezone).date()


def days_to_expiration(
    expiration: date | str,
    evaluated_at: datetime,
    *,
    market_timezone: ZoneInfo = MARKET_TIMEZONE,
) -> int:
    """Calendar DTE using the exchange-local day, never a UTC date."""

    return (parse_date(expiration) - market_date(evaluated_at, market_timezone=market_timezone)).days


def select_nearest_expiration(
    expirations: Iterable[date | str],
    evaluated_at: datetime,
    *,
    min_dte: int,
    max_dte: int,
    market_timezone: ZoneInfo = MARKET_TIMEZONE,
) -> date | None:
    selected = [
        parse_date(expiration)
        for expiration in expirations
        if min_dte <= days_to_expiration(expiration, evaluated_at, market_timezone=market_timezone) <= max_dte
    ]
    return min(selected, key=lambda item: (days_to_expiration(item, evaluated_at, market_timezone=market_timezone), item)) if selected else None


def is_timestamp_fresh(
    timestamp: datetime,
    *,
    evaluated_at: datetime,
    max_age_seconds: int,
) -> bool:
    """Accept only timestamps from now through the configured lookback window."""

    quote_at = parse_datetime(timestamp)
    reference = normalize_as_of(evaluated_at)
    age = (reference.astimezone(timezone.utc) - quote_at.astimezone(timezone.utc)).total_seconds()
    return 0 <= age <= max_age_seconds


def moving_average(values: Iterable[Any]) -> Decimal | None:
    parsed = [decimal(item) for item in values]
    parsed = [item for item in parsed if item is not None]
    if not parsed:
        return None
    return sum(parsed, Decimal("0")) / Decimal(len(parsed))


def quote_mid(quote: Any) -> Decimal | None:
    bid = decimal(value(quote, "bid"))
    ask = decimal(value(quote, "ask"))
    if bid is not None and ask is not None:
        return (bid + ask) / Decimal("2")
    if bid is not None:
        return bid
    return ask


def passes_top_of_book(quote: Any, *, max_bid_ask_spread_pct: Decimal) -> bool:
    bid = decimal(value(quote, "bid"))
    ask = decimal(value(quote, "ask"))
    if bid is None or ask is None or bid <= 0 or ask <= bid:
        return False
    mid = (bid + ask) / Decimal("2")
    return mid > 0 and ((ask - bid) / mid) <= max_bid_ask_spread_pct


def is_tradeable_long_leg(quote: Any) -> bool:
    bid = decimal(value(quote, "bid"))
    ask = decimal(value(quote, "ask"))
    return bid is not None and ask is not None and ask > Decimal("0") and ask > bid


def is_option_quote_fresh(
    quote: Any,
    *,
    evaluated_at: datetime,
    max_age_seconds: int,
) -> bool:
    raw_timestamp = value(quote, "timestamp")
    if raw_timestamp is None:
        return False
    return is_timestamp_fresh(
        parse_datetime(raw_timestamp),
        evaluated_at=evaluated_at,
        max_age_seconds=max_age_seconds,
    )


def option_quote_liquidity_reasons(
    quote: Any,
    *,
    evaluated_at: datetime,
    max_bid_ask_spread_pct: Decimal,
    min_volume: int,
    min_open_interest: int | None = None,
    max_age_seconds: int,
    label: str = "Option",
) -> list[str]:
    reasons: list[str] = []
    if not passes_top_of_book(quote, max_bid_ask_spread_pct=max_bid_ask_spread_pct):
        reasons.append(f"{label} does not have a tight, positive bid/ask.")
    if integer(value(quote, "volume"), 0) < min_volume:
        reasons.append(f"{label} volume is below the configured minimum {min_volume}.")
    if min_open_interest is not None and integer(value(quote, "open_interest"), 0) < min_open_interest:
        reasons.append(f"{label} open interest is below the configured minimum {min_open_interest}.")
    if not is_option_quote_fresh(quote, evaluated_at=evaluated_at, max_age_seconds=max_age_seconds):
        reasons.append(f"{label} quote is stale or has no trustworthy timestamp.")
    return reasons


def right_name(quote: Any) -> str:
    raw = value(quote, "right", "")
    return str(getattr(raw, "value", raw)).lower()
