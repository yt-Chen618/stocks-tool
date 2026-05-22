from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_execution_repository
from stocks_tool.domain.enums import BrokerName, OrderSide
from stocks_tool.domain.models import Execution
from stocks_tool.main import app


def build_execution() -> Execution:
    now = datetime(2026, 5, 22, 10, 4, tzinfo=timezone.utc)
    return Execution(
        id="execution-123",
        order_id="order-123",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id="1241940481017913344",
        external_execution_id="summary:1241940481017913344",
        symbol="UNH.US",
        side=OrderSide.BUY,
        quantity=1,
        price=Decimal("320.75"),
        executed_at=now,
        raw_payload={"source": "order_detail_summary"},
        created_at=now,
        updated_at=now,
    )


def with_execution_repository(repository: Mock) -> TestClient:
    app.dependency_overrides[get_execution_repository] = lambda: repository
    return TestClient(app)


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_list_executions_filters_by_account_and_order() -> None:
    repository = Mock()
    repository.list_executions.return_value = [build_execution()]

    client = with_execution_repository(repository)
    try:
        response = client.get(
            "/executions",
            params={
                "external_account_id": "LBPT10087357",
                "order_id": "order-123",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "execution-123"
    assert body[0]["quantity"] == 1
    assert body[0]["price"] == "320.75"
    assert body[0]["symbol"] == "UNH.US"
    repository.list_executions.assert_called_once_with(
        external_account_id="LBPT10087357",
        order_id="order-123",
    )
