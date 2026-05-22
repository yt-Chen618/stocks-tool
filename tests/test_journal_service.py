from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest

from stocks_tool.application.services.journal import JournalService
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    JournalEntryType,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from stocks_tool.domain.models import CreateJournalEntryRequest, Execution, JournalEntry, Order


def build_order() -> Order:
    now = datetime(2026, 5, 22, 10, 30, tzinfo=timezone.utc)
    return Order(
        id="order-123",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        trade_plan_id="plan-123",
        external_order_id="1241940481017913344",
        client_order_id="local-order-123",
        symbol="UNH.US",
        asset_type=AssetType.STOCK,
        side=OrderSide.BUY,
        quantity=2,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.FILLED,
        limit_price=Decimal("321.00"),
        stop_price=None,
        option_contract=None,
        raw_payload=None,
        submitted_at=now,
        created_at=now,
        updated_at=now,
    )


def build_execution(order_id: str = "order-123") -> Execution:
    now = datetime(2026, 5, 22, 10, 34, tzinfo=timezone.utc)
    return Execution(
        id="execution-123",
        order_id=order_id,
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id="1241940481017913344",
        external_execution_id="summary:1241940481017913344",
        symbol="UNH.US",
        side=OrderSide.BUY,
        quantity=2,
        price=Decimal("320.75"),
        executed_at=now,
        raw_payload=None,
        created_at=now,
        updated_at=now,
    )


def test_create_entry_links_order_and_execution_context() -> None:
    journals = Mock()
    journals.create_entry.side_effect = lambda entry: entry
    orders = Mock()
    orders.get_order.return_value = build_order()
    trade_plans = Mock()
    trade_plans.get_plan.return_value = object()
    executions = Mock()
    executions.get_execution.return_value = build_execution()
    service = JournalService(
        journals=journals,
        orders=orders,
        trade_plans=trade_plans,
        executions=executions,
    )

    created = service.create_entry(
        CreateJournalEntryRequest(
            external_account_id="LBPT10087357",
            symbol=" unh.us ",
            entry_type=JournalEntryType.REVIEW,
            title="  Post-trade review  ",
            notes="  Held the risk budget and respected the exit.  ",
            order_id="order-123",
            execution_id="execution-123",
            tags=[" discipline ", "execution", "discipline", ""],
        )
    )

    assert isinstance(created, JournalEntry)
    assert created.symbol == "UNH.US"
    assert created.trade_plan_id == "plan-123"
    assert created.order_id == "order-123"
    assert created.execution_id == "execution-123"
    assert created.title == "Post-trade review"
    assert created.notes == "Held the risk budget and respected the exit."
    assert created.tags == ["discipline", "execution"]


def test_create_entry_rejects_execution_order_mismatch() -> None:
    journals = Mock()
    orders = Mock()
    orders.get_order.return_value = build_order()
    trade_plans = Mock()
    executions = Mock()
    executions.get_execution.return_value = build_execution(order_id="order-999")
    service = JournalService(
        journals=journals,
        orders=orders,
        trade_plans=trade_plans,
        executions=executions,
    )

    with pytest.raises(ValueError, match="Linked execution does not belong to the linked order."):
        service.create_entry(
            CreateJournalEntryRequest(
                external_account_id="LBPT10087357",
                symbol="UNH.US",
                entry_type=JournalEntryType.REVIEW,
                title="Mismatch check",
                notes="Execution and order should align.",
                order_id="order-123",
                execution_id="execution-123",
            )
        )
