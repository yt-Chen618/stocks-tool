from datetime import datetime, timezone
from decimal import Decimal
import time
from unittest.mock import Mock

import pytest

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeBrokerAdapter,
    LongbridgeIntegrationError,
)
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import SecurityQuoteSnapshot


def build_adapter(**overrides) -> LongbridgeBrokerAdapter:
    settings = Settings(
        longbridge_request_timeout_seconds=1,
        longbridge_circuit_breaker_seconds=30,
        longbridge_executor_max_workers=1,
        **overrides,
    )
    return LongbridgeBrokerAdapter(settings=settings)


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
    assert second == cached_quote
    adapter._executor.shutdown(wait=False, cancel_futures=True)
