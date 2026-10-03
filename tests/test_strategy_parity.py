from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from stocks_tool.adapters.backtesting.rules import (
    FutureInformationError,
    bull_put_intents,
    covered_call_intents,
    zero_dte_intents,
)
from stocks_tool.adapters.backtesting.simulator import simulate_events
from stocks_tool.adapters.backtesting.lean_algorithms import algorithm_manifest, algorithm_source
from stocks_tool.domain.backtesting import BacktestStrategy, FeeModel, LifecycleModel, SlippageModel


NOW = datetime(2024, 1, 2, 15, tzinfo=timezone.utc)


def _bull_chain_event(*, long_bid: str = "0.95", long_ask: str = "1.00") -> dict:
    bars = [{"close": "100"}] * 30 + [{"close": "105"}] * 19 + [{"close": "110"}]
    return {
        "timestamp": NOW.isoformat(),
        "symbol": "SPY",
        "underlying_price": "110",
        "prev_close": "109",
        "open": "109.5",
        "bars": bars,
        "expiration_dates": ["2024-01-31"],
        "option_quotes": [
            {
                "symbol": "SPY240131P105",
                "expiration_date": "2024-01-31",
                "strike": "105",
                "right": "put",
                "delta": "-0.22",
                "open_interest": 500,
                "volume": 20,
                "bid": "2.00",
                "ask": "2.10",
                "timestamp": NOW.isoformat(),
            },
            {
                "symbol": "SPY240131P103",
                "expiration_date": "2024-01-31",
                "strike": "103",
                "right": "put",
                "delta": "-0.10",
                "open_interest": 500,
                "volume": 20,
                "bid": long_bid,
                "ask": long_ask,
                "timestamp": NOW.isoformat(),
            },
        ],
    }


def _simulate(strategy, events):
    return simulate_events(
        run_id="fixture",
        strategy=strategy,
        events=events,
        initial_cash=Decimal("100000"),
        fee_model=FeeModel(name="explicit", commission_per_contract=Decimal("0.65")),
        slippage_model=SlippageModel(name="explicit", basis_points=Decimal("5")),
        lifecycle_model=LifecycleModel(),
    )


def test_bull_put_requires_real_candidate_and_uses_configured_width_and_filters():
    intent = bull_put_intents([_bull_chain_event()])[0]
    assert intent.legs[0]["strike"] == "105"
    assert intent.legs[1]["strike"] == "103"
    assert intent.metadata["width"] == "2"
    assert bull_put_intents([{**_bull_chain_event(), "option_quotes": []}]) == []


def test_bull_put_liquidity_rejection_matches_preview_rules():
    assert bull_put_intents([_bull_chain_event(long_bid="0.90", long_ask="1.00")]) == []


def test_covered_call_selection_uses_dte_delta_otm_liquidity_and_cap():
    event = {
        "timestamp": NOW.isoformat(),
        "symbol": "AAPL",
        "underlying_price": "100",
        "shares": 250,
        "initial_stock_lots": [{"symbol": "AAPL", "quantity": 250, "acquisition_price": "100"}],
        "expiration_dates": ["2024-01-31"],
        "option_quotes": [
            {
                "symbol": "AAPL240131C104",
                "expiration_date": "2024-01-31",
                "strike": "104",
                "right": "call",
                "delta": "0.30",
                "open_interest": 200,
                "volume": 10,
                "bid": "1.00",
                "ask": "1.05",
                "timestamp": NOW.isoformat(),
            }
        ],
    }
    intent = covered_call_intents([event])[0]
    assert intent.legs[0]["quantity"] == 1
    assert intent.legs[0]["strike"] == "104"


def test_zero_dte_is_research_only_and_uses_exchange_local_date():
    event = {
        "timestamp": "2024-01-03T00:30:00+00:00",  # Jan 2, 19:30 ET
        "symbol": "QQQ",
        "underlying_price": "400",
        "direction": "call",
        "option_quotes": [
            {
                "symbol": "QQQ240102C400",
                "expiration_date": "2024-01-02",
                "strike": "400",
                "right": "call",
                "delta": "0.22",
                "open_interest": 200,
                "volume": 20,
                "bid": "0.50",
                "ask": "0.60",
                "timestamp": "2024-01-03T00:29:00+00:00",
            }
        ],
    }
    assert zero_dte_intents([event])
    intent = zero_dte_intents([event])[0]
    assert intent.action == "research_signal"


def test_future_information_is_rejected_for_candidates_and_lifecycle():
    with pytest.raises(FutureInformationError):
        bull_put_intents([{**_bull_chain_event(), "available_at": "2024-01-02T15:01:00Z"}])
    with pytest.raises(FutureInformationError):
        _simulate(
            BacktestStrategy.COVERED_CALL,
            [{
                "timestamp": "2024-01-02T15:00:00Z",
                "symbol": "SPY",
                "shares": 100,
                "call_strike": "105",
                "expiration": "2024-01-31",
                "fills": {"leg-0": {"quantity": 1, "price": "1"}},
                "lifecycle_events": [{"type": "expiry", "timestamp": "2024-01-02T15:01:00Z"}],
            }],
        )


def test_partial_legs_fees_and_assignment_stock_consequence_are_explicit():
    events = [
        {
            "timestamp": "2024-01-02T15:00:00Z",
            "symbol": "SPY",
            "underlying_price": "100",
            "short_put_strike": "105",
            "long_put_strike": "103",
            "expiration": "2024-01-31",
            "fills": {"leg-0": {"quantity": 1, "price": "2.00"}},
        },
        {
            "timestamp": "2024-01-31T21:00:00Z",
            "symbol": "SPY",
            "underlying_price": "100",
            "lifecycle_events": [{"type": "expiry", "underlying_price": "100"}],
        },
    ]
    result = _simulate(BacktestStrategy.BULL_PUT, events)
    assert result.trades[0].status == "partial"
    assert result.trades[0].fees > 0
    settlement = result.raw_payload["lifecycle_transitions"][0]
    assert settlement["assigned"]
    assert result.metrics["stock_positions"]["SPY"] == "100"


def test_open_option_without_a_mark_does_not_claim_a_complete_return():
    first = {
        "timestamp": "2024-01-02T15:00:00Z",
        "symbol": "SPY",
        "underlying_price": "100",
        "short_put_strike": "95",
        "long_put_strike": "93",
        "short_put_symbol": "SPY-SHORT",
        "long_put_symbol": "SPY-LONG",
        "expiration": "2024-01-31",
        "fills": {
            "SPY-SHORT": {"quantity": 1, "price": "1.00"},
            "SPY-LONG": {"quantity": 1, "price": "0.50"},
        },
    }
    result = _simulate(
        BacktestStrategy.BULL_PUT,
        [first, {"timestamp": "2024-01-03T15:00:00Z", "symbol": "SPY", "underlying_price": "101"}],
    )
    assert result.metrics["equity_mark_quality"] == "unavailable_open_option_marks"
    assert result.metrics["total_return_pct"] is None


def test_lean_registry_maps_real_algorithm_type_and_research_lock():
    bull = algorithm_manifest("bull_put")
    zero = algorithm_manifest("zero_dte")
    assert bull["algorithm_type"] == "StocksToolBullPutAlgorithm"
    assert bull["source"] == "algorithms.py"
    assert bull["source_sha256"]
    assert zero["research_only"] is True
    assert zero["algorithm_type"] == "StocksToolZeroDteResearchAlgorithm"


def test_formal_algorithm_source_applies_reality_models_and_quality_gates():
    source = algorithm_source("bull_put")
    assert "StocksToolFeeModel" in source
    assert "StocksToolSlippageModel" in source
    assert "StocksToolQuoteFillModel" in source
    assert "_new_order_group" in source
    assert "_on_bull_put_entry_protective_group" in source
    assert "bull_put_entry_short" in source
    assert "bull_put_exit_short" in source
    assert "bull_put_exit_long" in source
    assert "_consumed_quote_by_order_id" in source
    assert "is_fill_forward" in source
    assert "set_option_exercise_model" in source
    assert "set_option_assignment_model" in source
    assert "bull put close" in source
    assert "covered call close/roll" in source
    assert "active_account_spreads" in source
    assert "take_profit_exit_ratio" in source
    assert "stop_loss_exit_multiple" in source
    assert "_cash_after_initial_lots" in source
    assert "set_holdings" in source
    assert "_seed_stock_lots" in source
    assert "set_market_price" in source
    assert "TradeBar(" in source
    assert "Initial Stock Fees" in source
    assert "explicit_fee" in source


def test_zero_dte_uses_completed_daily_close_for_direction():
    source = algorithm_source("zero_dte")
    assert "_previous_daily_close" in source
    assert "_on_zero_dte_daily_bar" in source
    assert "security.price - security.close" not in source
    assert "TradeBarConsolidator" in source
    assert "missing_greeks" in source
    assert "formal strategy data quality failed" in source
