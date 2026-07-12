from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_zero_dte_lottery_strategy_service
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OptionRight,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from stocks_tool.domain.models import (
    Order,
    ZeroDteLotteryExecutionResult,
    ZeroDteLotteryPreviewResult,
    ZeroDteLotteryRuntimeState,
    ZeroDteLotteryScanResult,
)
from stocks_tool.main import app


NOW = datetime(2026, 6, 4, 14, 30, tzinfo=timezone.utc)


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_zero_dte_lottery_preview_route_returns_preview() -> None:
    service = Mock()
    service.preview.return_value = ZeroDteLotteryPreviewResult(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        evaluated_at=NOW,
        eligible=False,
        symbol="QQQ.US",
        direction=OptionRight.CALL,
        max_premium_per_trade=Decimal("150"),
        reasons=["No same-day option candidate passed delta, liquidity, freshness, volume/OI, and $150 premium filters."],
    )
    app.dependency_overrides[get_zero_dte_lottery_strategy_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.get(
            "/strategies/zero-dte-lottery/preview",
            params={
                "external_account_id": "LBPT10087357",
                "symbol": "QQQ.US",
                "direction": "call",
                "mode": "paper",
                "as_of": "2026-06-04T14:30:00Z",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["strategy_id"] == "zero_dte_lottery_v1"
    assert body["max_premium_per_trade"] == "150"
    assert body["direction"] == "call"
    request = service.preview.call_args.kwargs
    assert request["external_account_id"] == "LBPT10087357"
    assert request["symbol"] == "QQQ.US"
    assert request["direction"] == "call"
    assert request["mode"] == ExecutionMode.PAPER
    assert request["as_of"] == NOW


def test_zero_dte_lottery_execute_route_is_disabled_before_service_call() -> None:
    service = Mock()
    preview = ZeroDteLotteryPreviewResult(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        evaluated_at=NOW,
        eligible=True,
        symbol="QQQ.US",
        direction=OptionRight.CALL,
        max_premium_per_trade=Decimal("150"),
    )
    order = Order(
        id="order-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id="external-order-1",
        client_order_id="client-order-1",
        symbol="QQQ260604C736000.US",
        asset_type=AssetType.OPTION,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.SUBMITTED,
        limit_price=Decimal("1.45"),
        submitted_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    service.execute.return_value = ZeroDteLotteryExecutionResult(
        preview=preview,
        order=order,
        submitted_at=NOW,
    )
    app.dependency_overrides[get_zero_dte_lottery_strategy_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.post(
            "/strategies/zero-dte-lottery/execute",
            json={
                "external_account_id": "LBPT10087357",
                "symbol": "QQQ.US",
                "direction": "call",
                "mode": "paper",
                "as_of": "2026-06-04T14:30:00Z",
                "confirm_paper_order": True,
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "zero_dte_execution_disabled_pending_lifecycle"
    service.execute.assert_not_called()


def test_zero_dte_lottery_runtime_route_returns_state() -> None:
    service = Mock()
    service.get_runtime_state.return_value = ZeroDteLotteryRuntimeState(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        enabled=True,
        auto_execute_enabled=False,
        scan_interval_seconds=900,
        scan_window_start="10:00 ET",
        scan_window_end="14:30 ET",
        max_premium_per_trade=Decimal("150"),
        contracts_per_trade=1,
        max_trades_per_day=1,
        symbols=["QQQ.US"],
    )
    app.dependency_overrides[get_zero_dte_lottery_strategy_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.get(
            "/strategies/zero-dte-lottery/runtime",
            params={"external_account_id": "LBPT10087357", "mode": "paper"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["strategy_id"] == "zero_dte_lottery_v1"
    assert body["auto_execute_enabled"] is False
    request = service.get_runtime_state.call_args.kwargs
    assert request["external_account_id"] == "LBPT10087357"
    assert request["mode"] == ExecutionMode.PAPER


def test_zero_dte_lottery_runtime_update_route_rejects_auto_ordering() -> None:
    service = Mock()
    service.update_runtime_state.return_value = ZeroDteLotteryRuntimeState(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        enabled=True,
        auto_execute_enabled=True,
        scan_interval_seconds=900,
        scan_window_start="10:00 ET",
        scan_window_end="14:30 ET",
        max_premium_per_trade=Decimal("150"),
        contracts_per_trade=1,
        max_trades_per_day=1,
        symbols=["QQQ.US"],
    )
    app.dependency_overrides[get_zero_dte_lottery_strategy_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.post(
            "/strategies/zero-dte-lottery/runtime/LBPT10087357",
            params={"mode": "paper"},
            json={"auto_execute_enabled": True},
        )
    finally:
        clear_overrides()

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "zero_dte_execution_disabled_pending_lifecycle"
    service.update_runtime_state.assert_not_called()


def test_zero_dte_lottery_scan_route_returns_scan_result() -> None:
    service = Mock()
    service.run_scan.return_value = ZeroDteLotteryScanResult(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        scanned_at=NOW,
        executed=False,
        reason="Zero-DTE lottery auto-execution is disabled by configuration.",
    )
    app.dependency_overrides[get_zero_dte_lottery_strategy_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.post(
            "/strategies/zero-dte-lottery/runtime/LBPT10087357/scan",
            params={
                "symbol": "QQQ.US",
                "direction": "auto",
                "mode": "paper",
                "force": "false",
                "as_of": "2026-06-04T14:30:00Z",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["strategy_id"] == "zero_dte_lottery_v1"
    assert body["executed"] is False
    request = service.run_scan.call_args.kwargs
    assert request["external_account_id"] == "LBPT10087357"
    assert request["symbol"] == "QQQ.US"
    assert request["direction"] == "auto"
    assert request["force"] is False
    assert request["as_of"] == NOW


def test_zero_dte_lottery_force_scan_is_disabled_before_service_call() -> None:
    service = Mock()
    app.dependency_overrides[get_zero_dte_lottery_strategy_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.post(
            "/strategies/zero-dte-lottery/runtime/LBPT10087357/scan",
            params={"mode": "paper", "force": "true"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "zero_dte_execution_disabled_pending_lifecycle"
    service.run_scan.assert_not_called()
