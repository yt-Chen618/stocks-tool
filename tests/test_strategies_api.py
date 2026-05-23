from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_bull_put_strategy_service
from stocks_tool.domain.enums import BrokerName, ExecutionMode, SpreadStatus
from stocks_tool.domain.models import (
    BullPutSpread,
    BullPutSpreadMonitorResult,
    BullPutSpreadScanResult,
)
from stocks_tool.main import app


def with_strategy_service(service: Mock) -> TestClient:
    app.dependency_overrides[get_bull_put_strategy_service] = lambda: service
    return TestClient(app)


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_preview_bull_put_strategy_returns_scan_result() -> None:
    service = Mock()
    service.preview_spread.return_value = BullPutSpreadScanResult(
        symbol="QQQ.US",
        mode=ExecutionMode.PAPER,
        external_account_id="LBPT10087357",
        scanned_at=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
        eligible=False,
        reasons=["Bull put spread entries are only evaluated between 10:45 ET and 11:15 ET."],
        moving_average_20=Decimal("450.50"),
        moving_average_50=Decimal("430.25"),
    )

    client = with_strategy_service(service)
    try:
        response = client.get(
            "/strategies/bull-put/preview",
            params={
                "external_account_id": "LBPT10087357",
                "symbol": "QQQ.US",
                "mode": "paper",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "QQQ.US"
    assert body["eligible"] is False
    assert body["moving_average_20"] == "450.50"
    request = service.preview_spread.call_args.kwargs
    assert request["external_account_id"] == "LBPT10087357"


def test_preview_bull_put_strategy_maps_lookup_error_to_404() -> None:
    service = Mock()
    service.preview_spread.side_effect = LookupError("No local account snapshot was found for 'LBPT10087357'. Run account sync first.")

    client = with_strategy_service(service)
    try:
        response = client.get(
            "/strategies/bull-put/preview",
            params={
                "external_account_id": "LBPT10087357",
                "symbol": "QQQ.US",
                "mode": "paper",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "No local account snapshot was found for 'LBPT10087357'. Run account sync first."


def test_execute_bull_put_strategy_returns_spread() -> None:
    service = Mock()
    service.execute_spread.return_value = BullPutSpread(
        id="spread-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="QQQ.US",
        expiration_date=datetime(2026, 6, 19, tzinfo=timezone.utc).date(),
        contracts=1,
        width=Decimal("3"),
        long_symbol="QQQ260619P467000.US",
        long_strike=Decimal("467"),
        short_symbol="QQQ260619P470000.US",
        short_strike=Decimal("470"),
        status=SpreadStatus.OPEN,
        long_entry_order_id="long-entry",
        short_entry_order_id="short-entry",
        entry_long_price=Decimal("1.10"),
        entry_short_price=Decimal("2.40"),
        entry_net_credit=Decimal("1.30"),
        max_profit=Decimal("130.00"),
        max_loss=Decimal("170.00"),
        break_even=Decimal("468.70"),
        account_risk_pct=Decimal("0.0034"),
        entry_started_at=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
        opened_at=datetime(2026, 5, 22, 14, 46, tzinfo=timezone.utc),
        created_at=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 22, 14, 46, tzinfo=timezone.utc),
    )

    client = with_strategy_service(service)
    try:
        response = client.post(
            "/strategies/bull-put/execute",
            json={
                "external_account_id": "LBPT10087357",
                "symbol": "QQQ.US",
                "mode": "paper",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "spread-1"
    assert body["status"] == "open"
    request = service.execute_spread.call_args.args[0]
    assert request.external_account_id == "LBPT10087357"


def test_execute_bull_put_strategy_maps_value_error_to_400() -> None:
    service = Mock()
    service.execute_spread.side_effect = ValueError(
        "An active bull put spread already exists for 'QQQ.US' in account 'LBPT10087357'."
    )

    client = with_strategy_service(service)
    try:
        response = client.post(
            "/strategies/bull-put/execute",
            json={
                "external_account_id": "LBPT10087357",
                "symbol": "QQQ.US",
                "mode": "paper",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "An active bull put spread already exists for 'QQQ.US' in account 'LBPT10087357'."
    )


def test_monitor_bull_put_strategy_returns_monitor_result() -> None:
    service = Mock()
    spread = BullPutSpread(
        id="spread-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="QQQ.US",
        expiration_date=datetime(2026, 6, 19, tzinfo=timezone.utc).date(),
        contracts=1,
        width=Decimal("3"),
        long_symbol="QQQ260619P467000.US",
        long_strike=Decimal("467"),
        short_symbol="QQQ260619P470000.US",
        short_strike=Decimal("470"),
        status=SpreadStatus.CLOSED,
        short_exit_order_id="short-exit",
        long_exit_order_id="long-exit",
        entry_net_credit=Decimal("1.30"),
        exit_reason="take_profit",
        opened_at=datetime(2026, 5, 22, 14, 46, tzinfo=timezone.utc),
        closed_at=datetime(2026, 5, 23, 14, 46, tzinfo=timezone.utc),
        created_at=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 23, 14, 46, tzinfo=timezone.utc),
    )
    service.monitor_spread.return_value = BullPutSpreadMonitorResult(
        spread=spread,
        evaluated_at=datetime(2026, 5, 23, 14, 46, tzinfo=timezone.utc),
        should_close=True,
        exit_reason="take_profit",
        current_underlying_price=Decimal("501.25"),
        estimated_exit_debit=Decimal("0.50"),
        estimated_pnl=Decimal("80.00"),
        days_to_expiration=27,
    )

    client = with_strategy_service(service)
    try:
        response = client.post("/strategies/bull-put/spreads/spread-1/monitor")
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["should_close"] is True
    assert body["exit_reason"] == "take_profit"
    assert body["spread"]["status"] == "closed"
