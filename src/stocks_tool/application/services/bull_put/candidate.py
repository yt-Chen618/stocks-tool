from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from stocks_tool.domain.models import OptionMarketSnapshot


def select_expiration_date(
    *,
    expiry_dates: list[date],
    scanned_at: datetime,
    min_dte: int,
    max_dte: int,
    market_timezone: ZoneInfo,
) -> date | None:
    scanned_date = scanned_at.astimezone(market_timezone).date()
    candidates = [
        expiry_date
        for expiry_date in expiry_dates
        if min_dte <= (expiry_date - scanned_date).days <= max_dte
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda expiry_date: (expiry_date - scanned_date).days)


def is_short_put_candidate(
    quote: OptionMarketSnapshot,
    *,
    min_open_interest: int,
    short_delta_min: Decimal,
    short_delta_max: Decimal,
) -> bool:
    if quote.delta is None:
        return False
    if quote.open_interest is None or quote.open_interest < min_open_interest:
        return False
    delta_abs = abs(quote.delta)
    return short_delta_min <= delta_abs <= short_delta_max


def passes_top_of_book_filters(
    quote: OptionMarketSnapshot,
    *,
    max_bid_ask_spread_pct: Decimal,
) -> bool:
    if quote.bid is None or quote.ask is None:
        return False
    if quote.bid <= Decimal("0") or quote.ask <= quote.bid:
        return False
    mid = (quote.ask + quote.bid) / Decimal("2")
    if mid <= Decimal("0"):
        return False
    return ((quote.ask - quote.bid) / mid) <= max_bid_ask_spread_pct


def is_option_quote_fresh(
    quote: OptionMarketSnapshot,
    *,
    scanned_at: datetime,
    max_option_quote_age_seconds: int,
) -> bool:
    quote_time = quote.timestamp
    if quote_time.tzinfo is None:
        quote_time = quote_time.replace(tzinfo=timezone.utc)
    reference = scanned_at if scanned_at.tzinfo is not None else scanned_at.replace(tzinfo=timezone.utc)
    age_seconds = (reference.astimezone(timezone.utc) - quote_time.astimezone(timezone.utc)).total_seconds()
    if age_seconds < -300:
        return False
    return age_seconds <= max_option_quote_age_seconds


def option_leg_liquidity_reasons(
    *,
    short_leg: OptionMarketSnapshot,
    long_leg: OptionMarketSnapshot | None,
    scanned_at: datetime,
    max_bid_ask_spread_pct: Decimal,
    min_short_leg_volume: int,
    min_long_leg_volume: int,
    max_option_quote_age_seconds: int,
) -> list[str]:
    reasons: list[str] = []
    if not passes_top_of_book_filters(short_leg, max_bid_ask_spread_pct=max_bid_ask_spread_pct):
        reasons.append(f"Short put {short_leg.symbol} does not have a tight, positive bid/ask.")
    if short_leg.volume < min_short_leg_volume:
        reasons.append(
            f"Short put {short_leg.symbol} volume {short_leg.volume} is below the configured minimum {min_short_leg_volume}."
        )
    if not is_option_quote_fresh(
        short_leg,
        scanned_at=scanned_at,
        max_option_quote_age_seconds=max_option_quote_age_seconds,
    ):
        reasons.append(
            f"Short put {short_leg.symbol} quote timestamp is older than {max_option_quote_age_seconds}s."
        )
    if long_leg is None:
        return reasons
    if not passes_top_of_book_filters(long_leg, max_bid_ask_spread_pct=max_bid_ask_spread_pct):
        reasons.append(f"Long put {long_leg.symbol} does not have a tight, positive bid/ask.")
    if long_leg.volume < min_long_leg_volume:
        reasons.append(
            f"Long put {long_leg.symbol} volume {long_leg.volume} is below the configured minimum {min_long_leg_volume}."
        )
    if not is_option_quote_fresh(
        long_leg,
        scanned_at=scanned_at,
        max_option_quote_age_seconds=max_option_quote_age_seconds,
    ):
        reasons.append(
            f"Long put {long_leg.symbol} quote timestamp is older than {max_option_quote_age_seconds}s."
        )
    return reasons


def has_tradeable_long_leg(quote: OptionMarketSnapshot) -> bool:
    if quote.ask is None or quote.bid is None:
        return False
    if quote.ask <= Decimal("0"):
        return False
    return quote.ask > quote.bid


def entry_long_limit_price(
    *,
    long_leg: OptionMarketSnapshot,
    short_leg: OptionMarketSnapshot,
    width: Decimal,
    entry_long_limit_buffer: Decimal,
    min_conservative_credit_per_width_ratio: Decimal,
) -> Decimal | None:
    if long_leg.ask is None:
        return None
    buffered_price = long_leg.ask + entry_long_limit_buffer
    if short_leg.bid is None:
        return buffered_price
    min_credit_floor = width * min_conservative_credit_per_width_ratio
    max_price_for_credit = short_leg.bid - min_credit_floor
    if max_price_for_credit <= long_leg.ask:
        return long_leg.ask
    return min(buffered_price, max_price_for_credit)


def entry_long_price_ladder(
    *,
    ask_price: Decimal | None,
    capped_price: Decimal | None,
    entry_reprice_increment: Decimal,
    entry_reprice_max_steps: int,
) -> list[Decimal | None]:
    if ask_price is None:
        return []
    limit_cap = capped_price or ask_price
    return price_ladder(
        start=ask_price,
        end=max(ask_price, limit_cap),
        ascending=True,
        entry_reprice_increment=entry_reprice_increment,
        entry_reprice_max_steps=entry_reprice_max_steps,
    )


def entry_short_price_ladder(
    *,
    bid_price: Decimal | None,
    filled_long_price: Decimal | None,
    width: Decimal,
    entry_reprice_increment: Decimal,
    entry_reprice_max_steps: int,
    min_conservative_credit_per_width_ratio: Decimal,
) -> list[Decimal | None]:
    if bid_price is None:
        return []
    floor = bid_price
    if filled_long_price is not None:
        min_credit_floor = width * min_conservative_credit_per_width_ratio
        floor = max(
            floor - (entry_reprice_increment * entry_reprice_max_steps),
            filled_long_price + min_credit_floor,
        )
    return price_ladder(
        start=bid_price,
        end=min(bid_price, floor),
        ascending=False,
        entry_reprice_increment=entry_reprice_increment,
        entry_reprice_max_steps=entry_reprice_max_steps,
    )


def price_ladder(
    *,
    start: Decimal,
    end: Decimal,
    ascending: bool,
    entry_reprice_increment: Decimal,
    entry_reprice_max_steps: int,
) -> list[Decimal]:
    prices: list[Decimal] = [quantize_price(start)]
    current = start
    for _ in range(entry_reprice_max_steps):
        candidate = current + entry_reprice_increment if ascending else current - entry_reprice_increment
        if ascending and candidate >= end:
            break
        if not ascending and candidate <= end:
            break
        prices.append(quantize_price(candidate))
        current = candidate
    end_price = quantize_price(end)
    if prices[-1] != end_price:
        prices.append(end_price)
    return prices


def quantize_price(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def mid_price(quote: OptionMarketSnapshot) -> Decimal | None:
    if quote.bid is None or quote.ask is None:
        return None
    return (quote.bid + quote.ask) / Decimal("2")
