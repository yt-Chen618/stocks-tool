from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from stocks_tool.domain.strategies.bull_put import BullPutRules, is_short_put_candidate as select_is_short_put_candidate
from stocks_tool.domain.strategies.common import (
    is_option_quote_fresh as shared_is_option_quote_fresh,
    is_tradeable_long_leg as shared_is_tradeable_long_leg,
    passes_top_of_book as shared_passes_top_of_book,
    quote_mid as shared_quote_mid,
    select_nearest_expiration,
)
from stocks_tool.domain.models import OptionMarketSnapshot


def select_expiration_date(
    *,
    expiry_dates: list[date],
    scanned_at: datetime,
    min_dte: int,
    max_dte: int,
    market_timezone: ZoneInfo,
) -> date | None:
    return select_nearest_expiration(
        expiry_dates,
        scanned_at,
        min_dte=min_dte,
        max_dte=max_dte,
        market_timezone=market_timezone,
    )


def is_short_put_candidate(
    quote: OptionMarketSnapshot,
    *,
    min_open_interest: int,
    short_delta_min: Decimal,
    short_delta_max: Decimal,
) -> bool:
    return select_is_short_put_candidate(
        quote,
        rules=BullPutRules(
            min_open_interest=min_open_interest,
            short_delta_min=short_delta_min,
            short_delta_max=short_delta_max,
            require_trend=False,
        ),
    )


def passes_top_of_book_filters(
    quote: OptionMarketSnapshot,
    *,
    max_bid_ask_spread_pct: Decimal,
) -> bool:
    return shared_passes_top_of_book(
        quote,
        max_bid_ask_spread_pct=max_bid_ask_spread_pct,
    )


def is_option_quote_fresh(
    quote: OptionMarketSnapshot,
    *,
    scanned_at: datetime,
    max_option_quote_age_seconds: int,
) -> bool:
    return shared_is_option_quote_fresh(
        quote,
        evaluated_at=scanned_at,
        max_age_seconds=max_option_quote_age_seconds,
    )


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
    if not shared_passes_top_of_book(short_leg, max_bid_ask_spread_pct=max_bid_ask_spread_pct):
        reasons.append(f"Short put {short_leg.symbol} does not have a tight, positive bid/ask.")
    if short_leg.volume < min_short_leg_volume:
        reasons.append(
            f"Short put {short_leg.symbol} volume {short_leg.volume} is below the configured minimum {min_short_leg_volume}."
        )
    if not shared_is_option_quote_fresh(
        short_leg,
        evaluated_at=scanned_at,
        max_age_seconds=max_option_quote_age_seconds,
    ):
        reasons.append(
            f"Short put {short_leg.symbol} quote timestamp is older than {max_option_quote_age_seconds}s."
        )
    if long_leg is None:
        return reasons
    if not shared_passes_top_of_book(long_leg, max_bid_ask_spread_pct=max_bid_ask_spread_pct):
        reasons.append(f"Long put {long_leg.symbol} does not have a tight, positive bid/ask.")
    if long_leg.volume < min_long_leg_volume:
        reasons.append(
            f"Long put {long_leg.symbol} volume {long_leg.volume} is below the configured minimum {min_long_leg_volume}."
        )
    if not shared_is_option_quote_fresh(
        long_leg,
        evaluated_at=scanned_at,
        max_age_seconds=max_option_quote_age_seconds,
    ):
        reasons.append(
            f"Long put {long_leg.symbol} quote timestamp is older than {max_option_quote_age_seconds}s."
        )
    return reasons


def has_tradeable_long_leg(quote: OptionMarketSnapshot) -> bool:
    return shared_is_tradeable_long_leg(quote)


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
    return shared_quote_mid(quote) if quote.bid is not None and quote.ask is not None else None
