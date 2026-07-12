from datetime import datetime, timezone
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_longbridge_adapter, get_order_service
from stocks_tool.domain.enums import (
    BrokerName,
    ExecutionMode,
    TradingIntentState,
    TradingOperation,
)
from stocks_tool.domain.models import (
    BrokerOrderIntent,
    MarketDataModeRuntime,
    MarketDataOperationRuntime,
    MarketDataRuntimeSnapshot,
    TradeActionIntent,
)
from stocks_tool.main import app


def build_intent() -> BrokerOrderIntent:
    now = datetime(2026, 7, 11, 14, 30, tzinfo=timezone.utc)
    return BrokerOrderIntent(
        id="intent-1",
        trade_action_intent_id="action-1",
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        idempotency_key="strategy-order-key-0001",
        request_hash="a" * 64,
        operation=TradingOperation.SUBMIT,
        action="bull_put_entry_long",
        strategy_id="paper_bull_put_v1",
        entity_id="spread-1",
        leg="long_entry",
        broker_marker="st:0123456789abcdef",
        state=TradingIntentState.UNKNOWN,
        request_payload={"symbol": "QQQ.US"},
        last_error="broker response timed out",
        created_at=now,
        updated_at=now,
    )


def build_action() -> TradeActionIntent:
    now = datetime(2026, 7, 11, 14, 30, tzinfo=timezone.utc)
    return TradeActionIntent(
        id="action-1",
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        idempotency_key="bull-put-public-key-0001",
        request_hash="b" * 64,
        action="bull_put_execute",
        strategy_id="paper_bull_put_v1",
        entity_id="spread-1",
        state=TradingIntentState.SUBMITTING,
        request_payload={"symbol": "QQQ.US"},
        created_at=now,
        updated_at=now,
    )


def test_ops_lists_trading_intents_with_filters() -> None:
    service = Mock()
    service.list_trading_intents.return_value = [build_intent()]
    app.dependency_overrides[get_order_service] = lambda: service
    try:
        response = TestClient(app).get(
            "/ops/trading-intents",
            params={
                "external_account_id": "LBPT10087357",
                "mode": "paper",
                "state": "unknown",
                "limit": 25,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["id"] == "intent-1"
    assert response.json()[0]["state"] == "unknown"
    service.list_trading_intents.assert_called_once_with(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        state=TradingIntentState.UNKNOWN,
        limit=25,
    )


def test_ops_exposes_read_only_market_data_runtime_metrics() -> None:
    adapter = Mock()
    adapter.get_market_data_runtime_status.return_value = MarketDataRuntimeSnapshot(
        closed=False,
        sessions=[
            MarketDataModeRuntime(
                mode=ExecutionMode.PAPER,
                context_initialized=True,
                reference_cache_entries=1,
                pending_requests=0,
                max_pending_requests=2,
                operations=[
                    MarketDataOperationRuntime(
                        operation="option_expiry_dates",
                        request_count=2,
                        sdk_call_count=1,
                        cache_hit_count=1,
                        cache_miss_count=1,
                        success_count=2,
                        failure_count=0,
                        timeout_count=0,
                        last_latency_ms=1,
                        max_latency_ms=550,
                    )
                ],
            )
        ],
    )
    app.dependency_overrides[get_longbridge_adapter] = lambda: adapter
    try:
        response = TestClient(app).get("/ops/market-data-runtime")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["sessions"][0]["operations"][0]["cache_hit_count"] == 1
    adapter.get_market_data_runtime_status.assert_called_once_with()


def test_ops_gets_one_trading_intent_and_returns_404_when_missing() -> None:
    service = Mock()
    service.get_trading_intent.side_effect = [build_intent(), None]
    app.dependency_overrides[get_order_service] = lambda: service
    client = TestClient(app)
    try:
        found = client.get("/ops/trading-intents/intent-1")
        missing = client.get("/ops/trading-intents/missing")
    finally:
        app.dependency_overrides.clear()

    assert found.status_code == 200
    assert found.json()["broker_marker"] == "st:0123456789abcdef"
    assert missing.status_code == 404


def test_ops_exposes_parent_trade_actions_for_composite_recovery() -> None:
    service = Mock()
    service.list_trade_actions.return_value = [build_action()]
    service.get_trade_action.side_effect = [build_action(), None]
    app.dependency_overrides[get_order_service] = lambda: service
    client = TestClient(app)
    try:
        listed = client.get(
            "/ops/trade-actions",
            params={"external_account_id": "LBPT10087357", "state": "submitting"},
        )
        found = client.get("/ops/trade-actions/action-1")
        missing = client.get("/ops/trade-actions/missing")
    finally:
        app.dependency_overrides.clear()

    assert listed.status_code == 200
    assert listed.json()[0]["id"] == "action-1"
    assert found.status_code == 200
    assert found.json()["state"] == "submitting"
    assert missing.status_code == 404
    service.list_trade_actions.assert_called_once_with(
        external_account_id="LBPT10087357",
        mode=None,
        state=TradingIntentState.SUBMITTING,
        limit=100,
    )


def test_ops_no_order_resolution_requires_explicit_confirmation() -> None:
    service = Mock()
    service.resolve_trading_intent_no_order.side_effect = PermissionError(
        "Explicit paper no-order resolution confirmation is required."
    )
    app.dependency_overrides[get_order_service] = lambda: service
    try:
        response = TestClient(app).post(
            "/ops/trading-intents/intent-1/resolve-no-order",
            json={"confirm_paper_resolution": False},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "confirmation" in response.json()["detail"]
