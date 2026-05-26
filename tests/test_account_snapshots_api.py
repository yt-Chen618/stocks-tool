from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_account_snapshot_repository
from stocks_tool.domain.enums import AssetType, BrokerName
from stocks_tool.domain.models import AccountSnapshot, PositionSnapshot
from stocks_tool.main import app


def build_account_snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        id="snapshot-1",
        broker=BrokerName.LONGBRIDGE,
        account_id="LBPT10087357",
        currency="USD",
        cash_balance=Decimal("1912916.09"),
        net_liquidation=Decimal("1916789.09"),
        buying_power=Decimal("1915627.18"),
        positions=[
            PositionSnapshot(
                symbol="UNH.US",
                asset_type=AssetType.STOCK,
                quantity=Decimal("10"),
                average_cost=Decimal("388.35"),
                market_value=Decimal("3833.00"),
                unrealized_pnl=Decimal("-53.50"),
                raw_payload={"quote": {"last_done": "383.30"}},
            )
        ],
        raw_payload={"quotes": {"UNH.US": {"last_done": "383.30"}}},
        captured_at=datetime(2026, 5, 26, 2, 5, 34, tzinfo=timezone.utc),
    )


def with_account_snapshot_repository(repository: Mock) -> TestClient:
    app.dependency_overrides[get_account_snapshot_repository] = lambda: repository
    return TestClient(app)


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_get_latest_account_snapshot_returns_summary() -> None:
    repository = Mock()
    repository.get_latest_account_snapshot.return_value = build_account_snapshot()

    client = with_account_snapshot_repository(repository)
    try:
        response = client.get(
            "/account-snapshots/latest",
            params={"external_account_id": "LBPT10087357"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["account_id"] == "LBPT10087357"
    assert body["cash_balance"] == "1912916.09"
    assert body["positions"][0]["symbol"] == "UNH.US"
    assert "raw_payload" not in body
    assert "raw_payload" not in body["positions"][0]
    repository.get_latest_account_snapshot.assert_called_once_with(
        external_account_id="LBPT10087357"
    )


def test_get_latest_account_snapshot_returns_null_when_missing() -> None:
    repository = Mock()
    repository.get_latest_account_snapshot.return_value = None

    client = with_account_snapshot_repository(repository)
    try:
        response = client.get(
            "/account-snapshots/latest",
            params={"external_account_id": "LBPT10087357"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json() is None
