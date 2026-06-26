from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import time
from unittest.mock import Mock

import pytest

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeBrokerAdapter,
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
    LongbridgeIntegrationError,
)
from stocks_tool.application.services.broker_gateway import (
    BrokerGatewayFailureKind,
    broker_failure_reason_code,
    classify_broker_exception,
)
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import AccountSnapshot, SecurityQuoteSnapshot
from stocks_tool.ports.broker_gateway import (
    BrokerAccountGateway,
    BrokerMarketDataGateway,
    BrokerOrderGateway,
)


def build_adapter(**overrides) -> LongbridgeBrokerAdapter:
    settings = Settings(
        longbridge_request_timeout_seconds=1,
        longbridge_circuit_breaker_seconds=30,
        longbridge_executor_max_workers=1,
        **overrides,
    )
    return LongbridgeBrokerAdapter(settings=settings)


def test_default_longbridge_timeout_allows_slow_background_loads() -> None:
    settings = Settings()

    assert settings.longbridge_request_timeout_seconds == 20


def test_longbridge_adapter_satisfies_split_gateway_protocols() -> None:
    adapter = build_adapter()

    assert isinstance(adapter, BrokerMarketDataGateway)
    assert isinstance(adapter, BrokerOrderGateway)
    assert isinstance(adapter, BrokerAccountGateway)
    adapter._executor.shutdown(wait=False, cancel_futures=True)


def test_broker_gateway_failure_classifier_maps_common_longbridge_errors() -> None:
    assert classify_broker_exception(LongbridgeConfigurationError("missing token")).kind == (
        BrokerGatewayFailureKind.CONFIGURATION
    )
    assert classify_broker_exception(LongbridgeDependencyError("sdk missing")).retryable is False

    timeout = classify_broker_exception(LongbridgeIntegrationError("Longbridge action timed out after 20s."))
    assert timeout.kind == BrokerGatewayFailureKind.TIMEOUT
    assert timeout.retryable is True
    assert broker_failure_reason_code(timeout) == "market_data_unavailable"

    circuit = classify_broker_exception(LongbridgeIntegrationError("Skipping attempt to load quote for another 30s."))
    assert circuit.kind == BrokerGatewayFailureKind.CIRCUIT_OPEN
    assert broker_failure_reason_code(circuit) == "market_data_unavailable"

    rate_limit = classify_broker_exception(LongbridgeIntegrationError("Longbridge API returned 429 too many requests."))
    assert rate_limit.kind == BrokerGatewayFailureKind.RATE_LIMIT
    assert broker_failure_reason_code(rate_limit) == "broker_rate_limited"

    rejection = classify_broker_exception(LongbridgeIntegrationError("Broker rejected the order."))
    assert rejection.kind == BrokerGatewayFailureKind.BROKER_REJECTION
    assert rejection.retryable is False


def test_run_sdk_action_times_out_and_opens_circuit() -> None:
    adapter = build_adapter()

    with pytest.raises(LongbridgeIntegrationError, match="timed out"):
        adapter._run_sdk_action("load quote for 'QQQ.US'", lambda: time.sleep(2))

    with pytest.raises(LongbridgeIntegrationError, match="Skipping attempt"):
        adapter._run_sdk_action("load quote for 'QQQ.US'", lambda: "never-called")

    adapter._executor.shutdown(wait=False, cancel_futures=True)


def test_run_sdk_action_opens_circuit_on_connect_failure() -> None:
    adapter = build_adapter()

    with pytest.raises(LongbridgeIntegrationError, match="failed to load quote"):
        adapter._run_sdk_action(
            "load quote for 'SPY.US'",
            lambda: (_ for _ in ()).throw(RuntimeError("client error (Connect)")),
        )

    with pytest.raises(LongbridgeIntegrationError, match="Skipping attempt"):
        adapter._run_sdk_action("load quote for 'SPY.US'", lambda: "never-called")

    adapter._executor.shutdown(wait=False, cancel_futures=True)


def test_account_circuit_does_not_block_market_data_requests() -> None:
    adapter = build_adapter()

    with pytest.raises(LongbridgeIntegrationError, match="failed to build account snapshot"):
        adapter._run_sdk_action(
            "build account snapshot for 'LBPT10087357'",
            lambda: (_ for _ in ()).throw(RuntimeError("client error (Connect)")),
        )

    with pytest.raises(LongbridgeIntegrationError, match="Skipping attempt"):
        adapter._run_sdk_action("build account snapshot for 'LBPT10087357'", lambda: "never-called")

    assert adapter._run_sdk_action("load quotes for SPY.US, QQQ.US", lambda: "ok") == "ok"
    adapter._executor.shutdown(wait=False, cancel_futures=True)


def test_run_sdk_action_allows_non_network_errors_without_circuit() -> None:
    adapter = build_adapter()

    with pytest.raises(LongbridgeIntegrationError, match="No quote returned"):
        adapter._run_sdk_action(
            "load quote for 'EWY.US'",
            lambda: (_ for _ in ()).throw(LongbridgeIntegrationError("No quote returned for symbol 'EWY.US'.")),
        )

    assert adapter._run_sdk_action("load quote for 'EWY.US'", lambda: "ok") == "ok"
    adapter._executor.shutdown(wait=False, cancel_futures=True)


def test_get_quote_uses_recent_cache_after_transient_failure() -> None:
    adapter = build_adapter()
    cached_quote = SecurityQuoteSnapshot(
        symbol="SPY.US",
        last_done=Decimal("600"),
        prev_close=Decimal("598"),
        open=Decimal("599"),
        high=Decimal("601"),
        low=Decimal("597"),
        timestamp=datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc),
        volume=1_000_000,
        turnover=Decimal("600000000"),
        trade_status="Normal",
    )
    adapter._run_sdk_action = Mock(
        side_effect=[
            cached_quote,
            LongbridgeIntegrationError("Longbridge timed out while trying to load quote for 'SPY.US' after 6s."),
        ]
    )

    first = adapter.get_quote("SPY.US", ExecutionMode.PAPER)
    second = adapter.get_quote("SPY.US", ExecutionMode.PAPER)

    assert first == cached_quote
    assert second.model_dump(exclude={"data_quality", "warning_code", "warning_detail", "cache_age_seconds"}) == (
        cached_quote.model_dump(exclude={"data_quality", "warning_code", "warning_detail", "cache_age_seconds"})
    )
    assert second.data_quality == "cached"
    assert second.warning_code == "quote_cache_fallback"
    assert "timed out" in (second.warning_detail or "")
    assert second.cache_age_seconds is not None
    adapter._executor.shutdown(wait=False, cancel_futures=True)


def test_trade_order_listing_uses_timeout_guard() -> None:
    adapter = build_adapter()

    class SlowTradeContext:
        def __init__(self, config) -> None:
            self.config = config

        def today_orders(self, *, symbol=None, order_id=None):
            time.sleep(2)
            return []

    adapter._load_sdk = Mock(return_value={"TradeContext": SlowTradeContext})
    adapter._build_config = Mock(return_value=object())

    with pytest.raises(LongbridgeIntegrationError, match="timed out"):
        adapter.list_today_orders(mode=ExecutionMode.PAPER)

    with pytest.raises(LongbridgeIntegrationError, match="Skipping attempt"):
        adapter.list_today_orders(mode=ExecutionMode.PAPER)

    adapter._executor.shutdown(wait=False, cancel_futures=True)


def test_account_snapshot_uses_timeout_guard() -> None:
    adapter = build_adapter()
    snapshot = AccountSnapshot(
        broker=adapter.name,
        account_id="LBPT10087357",
        currency="USD",
        cash_balance=Decimal("100"),
        net_liquidation=Decimal("100"),
        buying_power=Decimal("100"),
        positions=[],
        captured_at=datetime(2026, 5, 29, 14, 0, tzinfo=timezone.utc),
    )
    adapter._run_sdk_action = Mock(return_value=snapshot)

    result = adapter.build_account_snapshot(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    )

    assert result == snapshot
    assert adapter._run_sdk_action.call_args.args[0] == "build account snapshot for 'LBPT10087357'"
    adapter._executor.shutdown(wait=False, cancel_futures=True)


def test_option_market_snapshot_maps_bid_ask_from_quote_payload() -> None:
    adapter = build_adapter()
    quote = SimpleNamespace(
        symbol="QQQ260619P470000.US",
        underlying_symbol="QQQ.US",
        expiry_date="2026-06-19",
        strike_price="470",
        direction="PUT",
        last_done="2.50",
        prev_close="2.30",
        open="2.40",
        high="2.65",
        low="2.35",
        timestamp=datetime(2026, 5, 29, 14, 0, tzinfo=timezone.utc),
        volume=2000,
        turnover="500000",
        trade_status="Normal",
        bid="2.40",
        ask="2.60",
        open_interest=500,
        implied_volatility="0.22",
        historical_volatility="0.18",
        contract_multiplier="100",
        contract_size=None,
        contract_type="Standard",
    )
    calc_index = SimpleNamespace(
        delta="-0.22",
        gamma="0.01",
        theta="-0.02",
        vega="0.05",
    )

    snapshot = adapter._map_option_market_snapshot(quote=quote, calc_index=calc_index)

    assert snapshot.bid == Decimal("2.40")
    assert snapshot.ask == Decimal("2.60")
    assert snapshot.raw_payload["quote"]["bid"] == "2.40"
    assert snapshot.raw_payload["quote"]["ask"] == "2.60"
    adapter._executor.shutdown(wait=False, cancel_futures=True)


def test_longbridge_datetime_normalizes_broker_wall_clock_labeled_as_utc() -> None:
    adapter = build_adapter()

    normalized = adapter._to_datetime(datetime(2026, 5, 29, 21, 56, tzinfo=timezone.utc))

    assert normalized == datetime(2026, 5, 29, 13, 56, tzinfo=timezone.utc)
    adapter._executor.shutdown(wait=False, cancel_futures=True)
