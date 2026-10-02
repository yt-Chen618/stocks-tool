from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from stocks_tool.application.services.bull_put.close import BullPutCloseOrchestrator
from stocks_tool.application.services.bull_put.execution import BullPutExecutionSupport
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    BrokerName,
    ExecutionMode,
    OptionRight,
    OrderSide,
    OrderStatus,
    OrderType,
    SpreadStatus,
    TimeInForce,
)
from stocks_tool.domain.models import (
    BullPutSpread,
    OptionMarketSnapshot,
    Order,
    RecoverBullPutCloseRequest,
)


NOW = datetime(2026, 5, 23, 14, 45, tzinfo=timezone.utc)


def _spread(**updates) -> BullPutSpread:
    base = BullPutSpread(
        id="spread-direct-close",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="QQQ.US",
        expiration_date=date(2026, 6, 19),
        contracts=1,
        width=Decimal("3"),
        long_symbol="QQQ260619P467000.US",
        long_strike=Decimal("467"),
        short_symbol="QQQ260619P470000.US",
        short_strike=Decimal("470"),
        status=SpreadStatus.OPEN,
        entry_net_credit=Decimal("1.30"),
        raw_payload={"monitor": {"should_close": True}},
        created_at=NOW,
        updated_at=NOW,
    )
    return base.model_copy(update=updates)


def _leg(symbol: str, strike: Decimal, *, bid: str = "1.00", ask: str = "1.20") -> OptionMarketSnapshot:
    return OptionMarketSnapshot(
        symbol=symbol,
        underlying_symbol="QQQ.US",
        expiration_date=date(2026, 6, 19),
        strike=strike,
        right=OptionRight.PUT,
        last_done=Decimal("1.10"),
        prev_close=Decimal("1.10"),
        open=Decimal("1.10"),
        high=Decimal("1.20"),
        low=Decimal("1.00"),
        timestamp=NOW,
        volume=20,
        turnover=Decimal("20"),
        bid=Decimal(bid),
        ask=Decimal(ask),
    )


def _order(order_id: str, symbol: str, side: OrderSide, status: OrderStatus) -> Order:
    return Order(
        id=order_id,
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id=f"remote-{order_id}",
        symbol=symbol,
        asset_type=None,
        side=side,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=status,
        executed_quantity=1 if status == OrderStatus.FILLED else 0,
        limit_price=Decimal("1.20"),
        created_at=NOW,
        updated_at=NOW,
    )


def _build_orchestrator(*, orders: Mock, spreads: Mock, market_data: Mock):
    support = BullPutExecutionSupport(
        strategy_settings=Settings().bull_put_strategy,
        orders=orders,
        spreads=spreads,
        market_data=market_data,
    )
    audit = Mock()
    return support, BullPutCloseOrchestrator(
        execution=support,
        mark_manual_action_required=Mock(side_effect=AssertionError("unexpected manual action")),
        validate_recover_close_request=Mock(),
        reject_recover_close=Mock(side_effect=AssertionError("unexpected recovery rejection")),
        append_recover_close_audit_event=audit,
    ), audit


def test_close_orchestrator_closes_short_before_long_with_shared_support() -> None:
    orders = Mock()
    spreads = Mock()
    market_data = Mock()
    spreads.update_spread.side_effect = lambda spread, **_updates: spread
    orders.submit_order.side_effect = [
        _order("short-exit", "QQQ260619P470000.US", OrderSide.BUY, OrderStatus.FILLED),
        _order("long-exit", "QQQ260619P467000.US", OrderSide.SELL, OrderStatus.FILLED),
    ]
    support, close, _audit = _build_orchestrator(orders=orders, spreads=spreads, market_data=market_data)

    result = close.close_after_monitor(
        spread=_spread(),
        reason="take_profit",
        short_leg=_leg("QQQ260619P470000.US", Decimal("470")),
        long_leg=_leg("QQQ260619P467000.US", Decimal("467")),
        parent_action_intent_id="parent-close",
    )

    assert result.status == SpreadStatus.CLOSED
    assert result.short_exit_order_id == "short-exit"
    assert result.long_exit_order_id == "long-exit"
    assert [call.args[0].side for call in orders.submit_order.call_args_list] == [OrderSide.BUY, OrderSide.SELL]
    assert all(
        call.kwargs["parent_action_intent_id"] == "parent-close"
        for call in orders.submit_order.call_args_list
    )


def test_recovery_orchestrator_replaces_failed_short_then_closes_long() -> None:
    orders = Mock()
    spreads = Mock()
    market_data = Mock()
    spread = _spread(
        short_exit_order_id="old-short-exit",
        latest_close_order_status="canceled",
    )
    spreads.update_spread.side_effect = lambda spread, **_updates: spread
    orders.refresh_order.return_value = _order(
        "old-short-exit",
        "QQQ260619P470000.US",
        OrderSide.BUY,
        OrderStatus.CANCELED,
    )
    orders.submit_order.side_effect = [
        _order("replacement-short", "QQQ260619P470000.US", OrderSide.BUY, OrderStatus.FILLED),
        _order("recovery-long", "QQQ260619P467000.US", OrderSide.SELL, OrderStatus.FILLED),
    ]
    market_data.get_option_market_snapshots.return_value = [
        _leg("QQQ260619P470000.US", Decimal("470"), ask="1.50"),
        _leg("QQQ260619P467000.US", Decimal("467"), bid="1.00"),
    ]
    support, close, audit = _build_orchestrator(orders=orders, spreads=spreads, market_data=market_data)
    request = RecoverBullPutCloseRequest(
        external_account_id="LBPT10087357",
        confirm_paper_order=True,
        max_debit=Decimal("2.00"),
    )
    started = []

    result = close.recover_close(
        spread=spread,
        request=request,
        idempotency_key="recovery-namespace",
        parent_action_intent_id="parent-recovery",
        on_broker_phase_started=lambda: started.append(True),
    )

    assert result.status == SpreadStatus.CLOSED
    assert result.short_exit_order_id == "replacement-short"
    assert result.long_exit_order_id == "recovery-long"
    assert started == [True]
    assert audit.call_count == 2
