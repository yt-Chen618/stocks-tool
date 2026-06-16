from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from stocks_tool.application.services.bull_put.candidate import (
    entry_long_limit_price,
    entry_long_price_ladder,
    entry_short_price_ladder,
    has_tradeable_long_leg,
    is_option_quote_fresh,
    is_short_put_candidate,
    mid_price,
    option_leg_liquidity_reasons,
    passes_top_of_book_filters,
    price_ladder,
    select_expiration_date,
)
from stocks_tool.domain.enums import OptionRight
from stocks_tool.domain.models import OptionMarketSnapshot


NOW = datetime(2026, 6, 15, 14, 45, tzinfo=timezone.utc)
NY = ZoneInfo("America/New_York")


def _put(symbol: str = "QQQ260717P700000.US", **updates) -> OptionMarketSnapshot:
    base = OptionMarketSnapshot(
        symbol=symbol,
        underlying_symbol="QQQ.US",
        expiration_date=date(2026, 7, 17),
        strike=Decimal("700"),
        right=OptionRight.PUT,
        last_done=Decimal("1.00"),
        prev_close=Decimal("0.95"),
        open=Decimal("0.90"),
        high=Decimal("1.10"),
        low=Decimal("0.80"),
        timestamp=NOW,
        volume=300,
        turnover=Decimal("120000"),
        bid=Decimal("1.00"),
        ask=Decimal("1.10"),
        open_interest=500,
        delta=Decimal("-0.22"),
    )
    return base.model_copy(update=updates)


def test_select_expiration_and_short_put_candidate_filters() -> None:
    assert select_expiration_date(
        expiry_dates=[date(2026, 7, 10), date(2026, 7, 17), date(2026, 8, 21)],
        scanned_at=NOW,
        min_dte=28,
        max_dte=35,
        market_timezone=NY,
    ) == date(2026, 7, 17)

    assert is_short_put_candidate(
        _put(),
        min_open_interest=200,
        short_delta_min=Decimal("0.18"),
        short_delta_max=Decimal("0.28"),
    )
    assert not is_short_put_candidate(
        _put(delta=Decimal("-0.10")),
        min_open_interest=200,
        short_delta_min=Decimal("0.18"),
        short_delta_max=Decimal("0.28"),
    )


def test_liquidity_and_quote_freshness_helpers() -> None:
    assert passes_top_of_book_filters(_put(), max_bid_ask_spread_pct=Decimal("0.20"))
    assert not passes_top_of_book_filters(_put(bid=Decimal("1.00"), ask=Decimal("1.80")), max_bid_ask_spread_pct=Decimal("0.20"))
    assert is_option_quote_fresh(
        _put(timestamp=NOW - timedelta(seconds=60)),
        scanned_at=NOW,
        max_option_quote_age_seconds=300,
    )
    assert not is_option_quote_fresh(
        _put(timestamp=NOW - timedelta(seconds=600)),
        scanned_at=NOW,
        max_option_quote_age_seconds=300,
    )

    reasons = option_leg_liquidity_reasons(
        short_leg=_put(volume=50),
        long_leg=_put("QQQ260717P697000.US", bid=Decimal("0.20"), ask=Decimal("0.80")),
        scanned_at=NOW,
        max_bid_ask_spread_pct=Decimal("0.20"),
        min_short_leg_volume=200,
        min_long_leg_volume=100,
        max_option_quote_age_seconds=300,
    )
    assert any("Short put" in reason and "volume" in reason for reason in reasons)
    assert any("Long put" in reason and "bid/ask" in reason for reason in reasons)


def test_entry_price_helpers_keep_credit_floor() -> None:
    long_leg = _put("QQQ260717P697000.US", bid=Decimal("0.40"), ask=Decimal("0.50"))
    short_leg = _put("QQQ260717P700000.US", bid=Decimal("1.00"), ask=Decimal("1.10"))

    assert has_tradeable_long_leg(long_leg)
    assert mid_price(short_leg) == Decimal("1.05")
    assert entry_long_limit_price(
        long_leg=long_leg,
        short_leg=short_leg,
        width=Decimal("3"),
        entry_long_limit_buffer=Decimal("0.05"),
        min_conservative_credit_per_width_ratio=Decimal("0.10"),
    ) == Decimal("0.55")
    assert entry_long_price_ladder(
        ask_price=Decimal("0.50"),
        capped_price=Decimal("0.60"),
        entry_reprice_increment=Decimal("0.02"),
        entry_reprice_max_steps=3,
    ) == [Decimal("0.50"), Decimal("0.52"), Decimal("0.54"), Decimal("0.56"), Decimal("0.60")]
    assert entry_short_price_ladder(
        bid_price=Decimal("1.00"),
        filled_long_price=Decimal("0.55"),
        width=Decimal("3"),
        entry_reprice_increment=Decimal("0.05"),
        entry_reprice_max_steps=3,
        min_conservative_credit_per_width_ratio=Decimal("0.10"),
    ) == [Decimal("1.00"), Decimal("0.95"), Decimal("0.90"), Decimal("0.85")]
    assert price_ladder(
        start=Decimal("1.00"),
        end=Decimal("0.90"),
        ascending=False,
        entry_reprice_increment=Decimal("0.03"),
        entry_reprice_max_steps=5,
    ) == [Decimal("1.00"), Decimal("0.97"), Decimal("0.94"), Decimal("0.91"), Decimal("0.90")]
