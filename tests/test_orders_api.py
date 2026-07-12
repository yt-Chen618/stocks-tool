from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from stocks_tool.adapters.brokers.longbridge import LongbridgeDependencyError
from stocks_tool.api.dependencies import get_order_service
from stocks_tool.application.services.orders import (
    TradingIntentConflictError,
    TradingIntentOutcomeUnknownError,
)
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
            headers={"Idempotency-Key": "ui-order-submit-0001"},
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
    assert service.submit_order.call_args.kwargs["idempotency_key"] == "ui-order-submit-0001"


def test_submit_order_requires_idempotency_key() -> None:
    service = Mock()
    client = with_order_service(service)
    try:
        response = client.post(
            "/orders/submit",
            json={
                "external_account_id": "LBPT10087357",
                "symbol": "UNH.US",
                "side": "buy",
                "quantity": 1,
                "order_type": "market",
                "mode": "paper",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 428
    assert response.json()["detail"]["code"] == "idempotency_key_required"
    service.submit_order.assert_not_called()


def test_submit_order_rejects_invalid_idempotency_key() -> None:
    service = Mock()
    client = with_order_service(service)
    try:
        response = client.post(
            "/orders/submit",
            headers={"Idempotency-Key": "too short"},
            json={
                "external_account_id": "LBPT10087357",
                "symbol": "UNH.US",
                "side": "buy",
                "quantity": 1,
                "order_type": "market",
                "mode": "paper",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "idempotency_key_invalid"
    service.submit_order.assert_not_called()


def test_submit_order_sets_replay_header_without_changing_body() -> None:
    service = Mock()
    service.submit_order.return_value = build_order().model_copy(
        update={"idempotent_replayed": True}
    )
    client = with_order_service(service)
    try:
        response = client.post(
            "/orders/submit",
            headers={"Idempotency-Key": "ui-order-submit-0002"},
            json={
                "external_account_id": "LBPT10087357",
                "symbol": "UNH.US",
                "side": "buy",
                "quantity": 1,
                "order_type": "market",
                "mode": "paper",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    assert response.headers["Idempotent-Replayed"] == "true"
    assert "idempotent_replayed" not in response.json()


def test_submit_order_maps_intent_conflict_to_structured_409() -> None:
    service = Mock()
    service.submit_order.side_effect = TradingIntentConflictError("intent-1")
    client = with_order_service(service)
    try:
        response = client.post(
            "/orders/submit",
            headers={"Idempotency-Key": "ui-order-submit-0003"},
            json={
                "external_account_id": "LBPT10087357",
                "symbol": "UNH.US",
                "side": "buy",
                "quantity": 1,
                "order_type": "market",
                "mode": "paper",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "idempotency_conflict",
        "intent_id": "intent-1",
        "retryable": False,
    }


def test_submit_order_maps_unknown_outcome_to_structured_409() -> None:
    service = Mock()
    service.submit_order.side_effect = TradingIntentOutcomeUnknownError("intent-2")
    client = with_order_service(service)
    try:
        response = client.post(
            "/orders/submit",
            headers={"Idempotency-Key": "ui-order-submit-0004"},
            json={
                "external_account_id": "LBPT10087357",
                "symbol": "UNH.US",
                "side": "buy",
                "quantity": 1,
                "order_type": "market",
                "mode": "paper",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "order_outcome_unknown",
        "intent_id": "intent-2",
        "retryable": False,
    }


def test_submit_order_maps_lookup_error_to_404() -> None:
    service = Mock()
    service.submit_order.side_effect = LookupError("No broker account was found for 'missing-account'.")

    client = with_order_service(service)
    try:
        response = client.post(
            "/orders/submit",
            headers={"Idempotency-Key": "ui-order-submit-0005"},
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
            headers={"Idempotency-Key": "ui-order-replace-0001"},
            json={
                "quantity": 1,
                "limit_price": None,
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 400
    assert response.json()["detail"] == "Replace limit price is required."


@pytest.mark.parametrize("operation", ["cancel", "replace"])
def test_existing_order_mutations_map_live_kill_switch_to_403(operation: str) -> None:
    service = Mock()
    getattr(service, f"{operation}_order").side_effect = PermissionError(
        "Live trading is disabled."
    )
    client = with_order_service(service)
    try:
        kwargs = {
            "headers": {"Idempotency-Key": f"ui-order-{operation}-live-0001"},
        }
        if operation == "replace":
            kwargs["json"] = {"quantity": 1, "limit_price": "541.00"}
        response = client.post(f"/orders/order-123/{operation}", **kwargs)
    finally:
        clear_overrides()

    assert response.status_code == 403
    assert response.json()["detail"] == "Live trading is disabled."


def test_cancel_order_maps_dependency_error_to_503() -> None:
    service = Mock()
    service.cancel_order.side_effect = LongbridgeDependencyError("Longbridge SDK is unavailable.")

    client = with_order_service(service)
    try:
        response = client.post(
            "/orders/order-123/cancel",
            headers={"Idempotency-Key": "ui-order-cancel-0001"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 503
    assert response.json()["detail"] == "Longbridge SDK is unavailable."
