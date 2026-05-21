from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.adapters.brokers.longbridge import LongbridgeDependencyError
from stocks_tool.api.dependencies import get_order_service
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from stocks_tool.domain.models import Order
from stocks_tool.main import app


def build_order(status: OrderStatus = OrderStatus.SUBMITTED) -> Order:
    now = datetime(2026, 5, 20, 14, 30, tzinfo=timezone.utc)
    return Order(
        id="order-123",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        trade_plan_id=None,
        external_order_id="1241723840942329856",
        client_order_id="local-abc123",
        symbol="UNH.US",
        asset_type=AssetType.STOCK,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=status,
        limit_price=Decimal("540.25"),
        stop_price=None,
        option_contract=None,
        raw_payload={"remote_order": {"id": "1241723840942329856"}},
        submitted_at=now,
        created_at=now,
        updated_at=now,
    )


def with_order_service(service: Mock) -> TestClient:
    app.dependency_overrides[get_order_service] = lambda: service
    return TestClient(app)


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_submit_order_returns_created_order() -> None:
    service = Mock()
    service.submit_order.return_value = build_order()

    client = with_order_service(service)
    try:
        response = client.post(
            "/orders/submit",
            json={
                "external_account_id": "LBPT10087357",
                "symbol": "UNH.US",
                "side": "buy",
                "quantity": 1,
                "order_type": "limit",
                "time_in_force": "day",
                "mode": "paper",
                "limit_price": 540.25,
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "order-123"
    assert body["symbol"] == "UNH.US"
    assert body["status"] == "submitted"
    request = service.submit_order.call_args.args[0]
    assert request.external_account_id == "LBPT10087357"
    assert request.order_type == OrderType.LIMIT


def test_submit_order_maps_lookup_error_to_404() -> None:
    service = Mock()
    service.submit_order.side_effect = LookupError("No broker account was found for 'missing-account'.")

    client = with_order_service(service)
    try:
        response = client.post(
            "/orders/submit",
            json={
                "external_account_id": "missing-account",
                "symbol": "UNH.US",
                "side": "buy",
                "quantity": 1,
                "order_type": "market",
                "time_in_force": "day",
                "mode": "paper",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "No broker account was found for 'missing-account'."


def test_replace_order_maps_value_error_to_400() -> None:
    service = Mock()
    service.replace_order.side_effect = ValueError("Replace limit price is required.")

    client = with_order_service(service)
    try:
        response = client.post(
            "/orders/order-123/replace",
            json={
                "quantity": 1,
                "limit_price": None,
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 400
    assert response.json()["detail"] == "Replace limit price is required."


def test_cancel_order_maps_dependency_error_to_503() -> None:
    service = Mock()
    service.cancel_order.side_effect = LongbridgeDependencyError("Longbridge SDK is unavailable.")

    client = with_order_service(service)
    try:
        response = client.post("/orders/order-123/cancel")
    finally:
        clear_overrides()

    assert response.status_code == 503
    assert response.json()["detail"] == "Longbridge SDK is unavailable."
