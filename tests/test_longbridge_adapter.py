from datetime import date, datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace
import threading
import time
from unittest.mock import Mock

import pytest

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeBrokerAdapter,
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
    LongbridgeIntegrationError,
    LongbridgeMutationOutcomeUnknownError,
)
from stocks_tool.application.services.broker_gateway import (
    BrokerGatewayFailureKind,
    broker_failure_reason_code,
    classify_broker_exception,
)
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    AssetType,
    ExecutionMode,
    OrderSide,
    OrderType,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    CreateOrderRequest,
    SecurityQuoteSnapshot,
)
from stocks_tool.ports.broker_gateway import (
    BrokerAccountGateway,
    BrokerMarketDataGateway,
    BrokerOrderGateway,
)


def build_adapter(**overrides) -> LongbridgeBrokerAdapter:
    settings_kwargs = {
        "longbridge_request_timeout_seconds": 1,
        "longbridge_circuit_breaker_seconds": 30,
        "longbridge_executor_max_workers": 1,
    }
    settings_kwargs.update(overrides)
    settings = Settings(
        **settings_kwargs,
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


def test_market_data_circuit_is_isolated_by_execution_mode() -> None:
    adapter = build_adapter()
    adapter._market_context = Mock(return_value=(object(), {}))

    def fail_connectivity(_context, _sdk):
        raise RuntimeError("client error (Connect)")

    with pytest.raises(LongbridgeIntegrationError, match="failed to load paper quote"):
        adapter._run_market_data_action(
            "load paper quote",
            ExecutionMode.PAPER,
            fail_connectivity,
            operation="quote",
        )

    assert (
        adapter._run_market_data_action(
            "load live quote",
            ExecutionMode.LIVE,
            lambda _context, _sdk: "live-ok",
            operation="quote",
        )
        == "live-ok"
    )

    with pytest.raises(LongbridgeIntegrationError, match="Skipping attempt"):
        adapter._run_market_data_action(
            "load paper quote again",
            ExecutionMode.PAPER,
            lambda _context, _sdk: "paper-never-called",
            operation="quote",
        )

    adapter.close()


def test_timed_out_sdk_mutation_is_unknown_and_quarantines_running_future() -> None:
    adapter = build_adapter(
        longbridge_executor_max_workers=2,
        longbridge_circuit_breaker_seconds=1,
    )
    object.__setattr__(adapter.settings, "longbridge_request_timeout_seconds", 0.05)
    started = threading.Event()
    release = threading.Event()
    second_started = threading.Event()
    caller = ThreadPoolExecutor(max_workers=1)

    def slow_mutation():
        started.set()
        release.wait(timeout=2)
        return "late-broker-response"

    try:
        first = caller.submit(
            adapter._run_sdk_action,
            "submit order for 'QQQ.US'",
            slow_mutation,
            mutation=True,
        )
        assert started.wait(timeout=1)
        with pytest.raises(LongbridgeMutationOutcomeUnknownError, match="outcome is unknown"):
            first.result(timeout=2)

        runtime = adapter.get_market_data_runtime_status()
        assert runtime.sdk_quarantine.pending_count == 1
        assert runtime.sdk_quarantine.oldest_started_at is not None
        assert runtime.sdk_quarantine.oldest_duration_seconds is not None
        assert runtime.sdk_quarantine.next_action

        adapter._circuit_open_until_by_key.clear()
        with pytest.raises(LongbridgeIntegrationError, match="timed-out SDK action is still running"):
            adapter._run_sdk_action(
                "submit order for 'QQQ.US' again",
                lambda: second_started.set(),
                mutation=True,
            )
        assert not second_started.is_set()
    finally:
        release.set()
        caller.shutdown(wait=True, cancel_futures=True)
        adapter.close()


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
    adapter._run_market_data_action = Mock(
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
    adapter.close()


def test_market_data_reuses_one_quote_context_per_mode_on_owner_thread() -> None:
    adapter = build_adapter()
    created_modes: list[object] = []
    call_threads: list[int] = []
    quote_calls = 0
    raw_quote = SimpleNamespace(symbol="SPY.US")
    mapped_quote = SecurityQuoteSnapshot(
        symbol="SPY.US",
        last_done=Decimal("600"),
        prev_close=Decimal("599"),
        open=Decimal("599"),
        high=Decimal("601"),
        low=Decimal("598"),
        timestamp=datetime(2026, 7, 11, 14, 0, tzinfo=timezone.utc),
        volume=1,
        turnover=Decimal("600"),
        trade_status="Normal",
    )

    class QuoteContext:
        def __init__(self, config) -> None:
            created_modes.append(config)

        def quote(self, symbols):
            nonlocal quote_calls
            quote_calls += 1
            call_threads.append(threading.get_ident())
            return [raw_quote]

        def option_chain_expiry_date_list(self, symbol):
            call_threads.append(threading.get_ident())
            return [datetime(2026, 7, 17, tzinfo=timezone.utc)]

    adapter._load_sdk = Mock(return_value={"QuoteContext": QuoteContext})
    adapter._build_config = Mock(side_effect=lambda mode, sdk: mode)
    adapter._map_security_quote = Mock(return_value=mapped_quote)

    assert adapter.get_quote("SPY.US", ExecutionMode.PAPER) == mapped_quote
    assert adapter.get_quote("SPY.US", ExecutionMode.PAPER) == mapped_quote
    assert adapter.list_option_expiry_dates("SPY.US", ExecutionMode.PAPER) == [
        datetime(2026, 7, 17, tzinfo=timezone.utc).date()
    ]
    assert len(created_modes) == 1
    assert len(set(call_threads)) == 1
    assert quote_calls == 2

    adapter.get_quote("SPY.US", ExecutionMode.LIVE)
    assert len(created_modes) == 2
    adapter.close()


def test_market_data_session_is_not_blocked_by_trade_executor_work() -> None:
    adapter = build_adapter()
    trade_started = threading.Event()
    release_trade = threading.Event()
    mapped_quote = SecurityQuoteSnapshot(
        symbol="SPY.US",
        last_done=Decimal("600"),
        prev_close=Decimal("599"),
        open=Decimal("599"),
        high=Decimal("601"),
        low=Decimal("598"),
        timestamp=datetime(2026, 7, 11, 14, 0, tzinfo=timezone.utc),
        volume=1,
        turnover=Decimal("600"),
        trade_status="Normal",
    )

    class QuoteContext:
        def __init__(self, config) -> None:
            pass

        def quote(self, symbols):
            return [SimpleNamespace(symbol=symbols[0])]

    adapter._load_sdk = Mock(return_value={"QuoteContext": QuoteContext})
    adapter._build_config = Mock(return_value=object())
    adapter._map_security_quote = Mock(return_value=mapped_quote)

    def slow_trade_action():
        trade_started.set()
        release_trade.wait(timeout=1)
        return "trade-finished"

    with ThreadPoolExecutor(max_workers=1) as caller:
        trade_future = caller.submit(
            adapter._run_sdk_action,
            "list today orders for 'account'",
            slow_trade_action,
        )
        assert trade_started.wait(timeout=1)
        assert adapter.get_quote("SPY.US", ExecutionMode.PAPER) == mapped_quote
        assert trade_future.done() is False
        release_trade.set()
        assert trade_future.result(timeout=1) == "trade-finished"
    adapter.close()


def test_market_data_queue_saturation_rejects_and_releases_slot() -> None:
    adapter = build_adapter(
        longbridge_market_data_max_pending_requests=1,
        longbridge_executor_max_workers=1,
    )
    started = threading.Event()
    release = threading.Event()
    caller = ThreadPoolExecutor(max_workers=1)
    adapter._market_context = Mock(return_value=(object(), {}))

    def blocked_action(_context, _sdk):
        started.set()
        release.wait(timeout=2)
        return "first"

    try:
        first = caller.submit(
            adapter._run_market_data_action,
            "queue saturation first",
            ExecutionMode.PAPER,
            blocked_action,
            operation="queue_saturation",
        )
        assert started.wait(timeout=1)
        with pytest.raises(LongbridgeIntegrationError, match="queue is full"):
            adapter._run_market_data_action(
                "queue saturation second",
                ExecutionMode.PAPER,
                lambda _context, _sdk: "never-called",
                operation="queue_saturation",
            )
        release.set()
        assert first.result(timeout=2) == "first"
        assert (
            adapter._run_market_data_action(
                "queue saturation after release",
                ExecutionMode.PAPER,
                lambda _context, _sdk: "after-release",
                operation="queue_saturation",
            )
            == "after-release"
        )
        runtime = adapter.get_market_data_runtime_status()
        session = next(item for item in runtime.sessions if item.mode == ExecutionMode.PAPER)
        assert session.pending_requests == 0
        assert session.max_pending_requests == 1
    finally:
        release.set()
        caller.shutdown(wait=True, cancel_futures=True)
        adapter.close()


def test_market_data_cancelled_queued_future_releases_slot() -> None:
    adapter = build_adapter(
        longbridge_market_data_max_pending_requests=2,
        longbridge_executor_max_workers=1,
    )
    started = threading.Event()
    release = threading.Event()
    adapter._market_context = Mock(return_value=(object(), {}))

    def occupy_session_executor():
        started.set()
        release.wait(timeout=2)
        return "occupier-finished"

    try:
        session = adapter._get_market_session(ExecutionMode.PAPER)
        occupier = session.executor.submit(occupy_session_executor)
        assert started.wait(timeout=1)
        with pytest.raises(LongbridgeIntegrationError, match="timed out"):
            adapter._run_market_data_action(
                "cancel queue second",
                ExecutionMode.PAPER,
                lambda _context, _sdk: "never-called",
                operation="cancel_queue",
            )
        runtime = adapter.get_market_data_runtime_status()
        session = next(item for item in runtime.sessions if item.mode == ExecutionMode.PAPER)
        assert session.pending_requests == 0
        release.set()
        assert occupier.result(timeout=2) == "occupier-finished"
        adapter._circuit_open_until_by_key.clear()
        assert (
            adapter._run_market_data_action(
                "cancel queue after release",
                ExecutionMode.PAPER,
                lambda _context, _sdk: "after-cancel",
                operation="cancel_queue",
            )
            == "after-cancel"
        )
    finally:
        release.set()
        adapter.close()


def test_reference_cache_is_isolated_by_execution_mode_for_same_key() -> None:
    adapter = build_adapter(longbridge_reference_data_cache_ttl_seconds=300)
    sdk_calls: list[ExecutionMode] = []

    class QuoteContext:
        def __init__(self, config) -> None:
            self.config = config

        def option_chain_expiry_date_list(self, symbol):
            sdk_calls.append(self.config)
            return [datetime(2026, 7, 17, tzinfo=timezone.utc)]

    adapter._load_sdk = Mock(return_value={"QuoteContext": QuoteContext})
    adapter._build_config = Mock(side_effect=lambda mode, sdk: mode)

    try:
        adapter.list_option_expiry_dates("SPY.US", ExecutionMode.PAPER)
        adapter.list_option_expiry_dates("SPY.US", ExecutionMode.PAPER)
        adapter.list_option_expiry_dates("SPY.US", ExecutionMode.LIVE)
        adapter.list_option_expiry_dates("SPY.US", ExecutionMode.LIVE)
        assert sdk_calls == [ExecutionMode.PAPER, ExecutionMode.LIVE]
    finally:
        adapter.close()


def test_market_session_close_failure_still_releases_context_and_executor() -> None:
    adapter = build_adapter()
    session = adapter._get_market_session(ExecutionMode.PAPER)
    context = Mock()
    context.close.side_effect = RuntimeError("close failed")
    session.context = context
    session.sdk = {}

    adapter.close()

    assert adapter._closed is True
    assert session.context is None
    assert session.sdk is None


def test_reference_data_cache_coalesces_concurrent_expiry_reads() -> None:
    adapter = build_adapter(longbridge_reference_data_cache_ttl_seconds=300)
    sdk_started = threading.Event()
    release_sdk = threading.Event()
    sdk_calls = 0

    class QuoteContext:
        def __init__(self, config) -> None:
            pass

        def option_chain_expiry_date_list(self, symbol):
            nonlocal sdk_calls
            sdk_calls += 1
            sdk_started.set()
            release_sdk.wait(timeout=1)
            return [datetime(2026, 7, 17, tzinfo=timezone.utc)]

    adapter._load_sdk = Mock(return_value={"QuoteContext": QuoteContext})
    adapter._build_config = Mock(return_value=object())

    with ThreadPoolExecutor(max_workers=2) as callers:
        first = callers.submit(
            adapter.list_option_expiry_dates,
            "SPY.US",
            ExecutionMode.PAPER,
        )
        assert sdk_started.wait(timeout=1)
        second = callers.submit(
            adapter.list_option_expiry_dates,
            "SPY.US",
            ExecutionMode.PAPER,
        )
        release_sdk.set()
        assert first.result(timeout=1) == [date(2026, 7, 17)]
        assert second.result(timeout=1) == [date(2026, 7, 17)]

    assert sdk_calls == 1
    runtime = adapter.get_market_data_runtime_status()
    paper = next(item for item in runtime.sessions if item.mode == ExecutionMode.PAPER)
    expiry_stats = next(
        item for item in paper.operations if item.operation == "option_expiry_dates"
    )
    assert expiry_stats.request_count == 2
    assert expiry_stats.sdk_call_count == 1
    assert expiry_stats.cache_hit_count == 1
    assert expiry_stats.cache_miss_count == 1
    assert paper.reference_cache_entries == 1
    assert paper.max_pending_requests == 2
    adapter.close()


def test_reference_data_cache_returns_defensive_option_chain_copies() -> None:
    adapter = build_adapter(longbridge_reference_data_cache_ttl_seconds=300)
    sdk_calls = 0

    class QuoteContext:
        def __init__(self, config) -> None:
            pass

        def option_chain_info_by_date(self, symbol, expiry_date):
            nonlocal sdk_calls
            sdk_calls += 1
            return [
                SimpleNamespace(
                    price=Decimal("600"),
                    call_symbol="SPY260717C600000.US",
                    put_symbol="SPY260717P600000.US",
                    standard=True,
                )
            ]

    adapter._load_sdk = Mock(return_value={"QuoteContext": QuoteContext})
    adapter._build_config = Mock(return_value=object())

    first = adapter.list_option_chain("SPY.US", date(2026, 7, 17), ExecutionMode.PAPER)
    first[0].strike = Decimal("1")
    second = adapter.list_option_chain("SPY.US", date(2026, 7, 17), ExecutionMode.PAPER)

    assert second[0].strike == Decimal("600")
    assert sdk_calls == 1
    adapter.close()


def test_reference_data_cache_is_bounded_and_evicts_oldest_entry() -> None:
    adapter = build_adapter(
        longbridge_reference_data_cache_ttl_seconds=300,
        longbridge_reference_data_cache_max_entries=1,
    )
    sdk_calls = 0

    class QuoteContext:
        def __init__(self, config) -> None:
            pass

        def option_chain_expiry_date_list(self, symbol):
            nonlocal sdk_calls
            sdk_calls += 1
            return [datetime(2026, 7, 17, tzinfo=timezone.utc)]

    adapter._load_sdk = Mock(return_value={"QuoteContext": QuoteContext})
    adapter._build_config = Mock(return_value=object())

    adapter.list_option_expiry_dates("SPY.US", ExecutionMode.PAPER)
    adapter.list_option_expiry_dates("QQQ.US", ExecutionMode.PAPER)
    adapter.list_option_expiry_dates("SPY.US", ExecutionMode.PAPER)

    assert sdk_calls == 3
    adapter.close()


def test_prewarm_market_data_only_loads_read_only_quotes() -> None:
    adapter = build_adapter()
    adapter.get_quotes = Mock(return_value={})

    adapter.prewarm_market_data(
        mode=ExecutionMode.PAPER,
        symbols=["SPY.US", "QQQ.US"],
    )

    adapter.get_quotes.assert_called_once_with(["SPY.US", "QQQ.US"], ExecutionMode.PAPER)
    adapter.close()


def test_market_data_runtime_status_does_not_initialize_a_session() -> None:
    adapter = build_adapter()

    runtime = adapter.get_market_data_runtime_status()

    assert runtime.closed is False
    assert runtime.sessions == []
    adapter.close()


def test_market_data_runtime_records_timeout_and_circuit_rejection() -> None:
    adapter = build_adapter()

    class SlowQuoteContext:
        def __init__(self, config) -> None:
            pass

        def quote(self, symbols):
            time.sleep(2)
            return []

    adapter._load_sdk = Mock(return_value={"QuoteContext": SlowQuoteContext})
    adapter._build_config = Mock(return_value=object())

    with pytest.raises(LongbridgeIntegrationError, match="timed out"):
        adapter.get_quote("SPY.US", ExecutionMode.PAPER)
    with pytest.raises(LongbridgeIntegrationError, match="Skipping attempt"):
        adapter.get_quote("SPY.US", ExecutionMode.PAPER)

    runtime = adapter.get_market_data_runtime_status()
    quote_stats = runtime.sessions[0].operations[0]
    assert quote_stats.operation == "quote"
    assert quote_stats.request_count == 2
    assert quote_stats.failure_count == 2
    assert quote_stats.timeout_count == 1
    adapter.close()


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


def test_history_order_listing_exposes_recovery_remark() -> None:
    adapter = build_adapter()
    detail = SimpleNamespace(
        order_id="external-order-1",
        symbol="UNH.US",
        side="BUY",
        quantity=Decimal("1"),
        order_type="LO",
        time_in_force="DAY",
        status="NEW",
        price=Decimal("321.00"),
        trigger_price=None,
        executed_quantity=Decimal("0"),
        executed_price=None,
        remark="st:0123456789abcdef operator note",
        submitted_at=datetime(2026, 7, 11, 14, 30, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 11, 14, 31, tzinfo=timezone.utc),
    )

    class TradeContext:
        def __init__(self, config) -> None:
            self.config = config

        def history_orders(self, *, symbol=None, start_at=None, end_at=None):
            return [detail]

    adapter._load_sdk = Mock(return_value={"TradeContext": TradeContext})
    adapter._build_config = Mock(return_value=object())

    orders = adapter.list_history_orders(mode=ExecutionMode.PAPER)

    assert orders[0].remark == "st:0123456789abcdef operator note"
    assert orders[0].raw_payload["remark"] == "st:0123456789abcdef operator note"
    adapter._executor.shutdown(wait=False, cancel_futures=True)


@pytest.mark.parametrize("returned_count", [1000, 1001])
def test_history_order_listing_rejects_saturated_page_as_incomplete(
    returned_count: int,
) -> None:
    adapter = build_adapter()

    class TradeContext:
        def __init__(self, config) -> None:
            self.config = config

        def history_orders(self, *, symbol=None, start_at=None, end_at=None):
            return [object()] * returned_count

    adapter._load_sdk = Mock(return_value={"TradeContext": TradeContext})
    adapter._build_config = Mock(return_value=object())

    with pytest.raises(LongbridgeIntegrationError, match="history order coverage is incomplete"):
        adapter.list_history_orders(mode=ExecutionMode.PAPER)

    adapter.close()


def test_submit_detail_failure_after_order_id_is_explicitly_unknown() -> None:
    adapter = build_adapter()

    class TradeContext:
        def __init__(self, config) -> None:
            self.config = config

        def submit_order(self, **kwargs):
            return SimpleNamespace(order_id="external-order-after-submit")

        def order_detail(self, external_order_id):
            raise RuntimeError("broker rejected detail lookup")

    adapter._load_sdk = Mock(return_value={"TradeContext": TradeContext})
    adapter._build_config = Mock(return_value=object())
    adapter._map_submit_order_type = Mock(return_value=object())
    adapter._map_submit_time_in_force = Mock(return_value=object())
    adapter._map_submit_side = Mock(return_value=object())

    with pytest.raises(LongbridgeMutationOutcomeUnknownError) as caught:
        adapter.submit_order(
            CreateOrderRequest(
                external_account_id="LBPT10087357",
                symbol="UNH260626C105000.US",
                asset_type=AssetType.OPTION,
                side=OrderSide.SELL,
                quantity=1,
                order_type=OrderType.LIMIT,
                mode=ExecutionMode.PAPER,
                limit_price=Decimal("1.20"),
            )
        )

    assert caught.value.external_order_id == "external-order-after-submit"
    adapter._executor.shutdown(wait=False, cancel_futures=True)


def test_position_symbol_recognizes_option_even_when_position_channel_has_no_asset_type() -> None:
    adapter = build_adapter()
    position = SimpleNamespace(
        symbol="UNH260626C105000.US",
        quantity=Decimal("-1"),
        cost_price=Decimal("1.20"),
    )

    snapshot = adapter._map_position_snapshot(position, quote=None)

    assert snapshot.asset_type == AssetType.OPTION
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
