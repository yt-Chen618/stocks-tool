from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from stocks_tool.adapters.backtesting.lean_algorithms.reality_models import (
    ExecutableQuote,
    QuoteFreshnessError,
    RealityModelError,
    build_contract_quote_payload,
    observed_at,
)


NOW = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)


def _quote(**overrides):
    value = {
        "bid": "1.00",
        "ask": "1.20",
        "bid_size": 1,
        "ask_size": 2,
        "timestamp": NOW - timedelta(seconds=5),
    }
    value.update(overrides)
    return value


def test_quote_payload_uses_source_observation_time_instead_of_algorithm_now():
    quote = _quote(timestamp=NOW - timedelta(minutes=3))

    payload = build_contract_quote_payload(quote)

    assert payload["timestamp"] == NOW - timedelta(minutes=3)
    assert observed_at(quote) != NOW


def test_naive_lean_contract_time_is_exchange_local_before_utc_conversion():
    quote = _quote(timestamp=datetime(2024, 1, 2, 10, 0))

    assert observed_at(quote) == datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)


def test_buy_uses_ask_sell_uses_bid_and_displayed_size_caps_partial_fill():
    quote = ExecutableQuote.from_contract(_quote())

    buy_quantity, buy_price = quote.fill("buy", Decimal("5"))
    sell_quantity, sell_price = quote.fill("sell", Decimal("5"))

    assert (buy_quantity, buy_price) == (Decimal("2"), Decimal("1.20"))
    assert (sell_quantity, sell_price) == (Decimal("1"), Decimal("1.00"))
    assert buy_price != (quote.bid + quote.ask) / Decimal("2")


def test_missing_or_zero_displayed_size_cannot_be_treated_as_unlimited():
    with pytest.raises(RealityModelError, match="size must be positive"):
        ExecutableQuote.from_contract(_quote(ask_size=0))


def test_freshness_rejects_future_and_stale_quotes():
    future = ExecutableQuote.from_contract(_quote(timestamp=NOW + timedelta(seconds=1)))
    stale = ExecutableQuote.from_contract(_quote(timestamp=NOW - timedelta(seconds=31)))

    with pytest.raises(QuoteFreshnessError, match="after the evaluation time"):
        future.require_fresh(evaluated_at=NOW, max_age_seconds=30)
    with pytest.raises(QuoteFreshnessError, match="stale"):
        stale.require_fresh(evaluated_at=NOW, max_age_seconds=30)


def test_missing_timestamp_is_not_replaced_by_current_algorithm_time():
    assert observed_at(_quote(timestamp=None)) is None
    with pytest.raises(QuoteFreshnessError, match="timestamp"):
        ExecutableQuote.from_contract(_quote(timestamp=None))
