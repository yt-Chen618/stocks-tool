from datetime import date
from decimal import Decimal

from scripts.run_bull_put_strategy_regression import FakeOrderService
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OptionRight,
    OrderSide,
    OrderType,
    TimeInForce,
    TradingIntentState,
)
from stocks_tool.domain.models import (
    CreateOrderRequest,
    OptionContractRef,
    TradingActionContext,
)


def _request() -> CreateOrderRequest:
    return CreateOrderRequest(
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        symbol="QQQ260619P470000.US",
        asset_type=AssetType.OPTION,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        limit_price=Decimal("1.10"),
        option_contract=OptionContractRef(
            underlying_symbol="QQQ.US",
            expiration_date=date(2026, 6, 19),
            strike=Decimal("470"),
            right=OptionRight.PUT,
        ),
    )


def test_fake_order_service_persists_parent_child_and_replays_child() -> None:
    service = FakeOrderService()
    context = TradingActionContext(
        action="bull_put_entry",
        strategy_id="paper_bull_put_v1",
        entity_id="spread-1",
        leg="long_entry",
    )
    parent = service.prepare_trade_action(
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        idempotency_key="parent-key",
        request_hash="parent-hash",
        action_context=context,
        request_payload={"spread_id": "spread-1"},
    )
    service.mark_trade_action_submitting(parent.intent.id)
    request = _request()
    order = service.submit_order(
        request,
        idempotency_key="child-key",
        action_context=context,
        parent_action_intent_id=parent.intent.id,
    )
    service.complete_trade_action(parent.intent.id, {"spread_id": "spread-1"})

    child = service.trading_intents[order.order_intent_id or ""]
    assert service.actions[parent.intent.id].state == TradingIntentState.PERSISTED
    assert child.trade_action_intent_id == parent.intent.id
    assert child.state == TradingIntentState.PERSISTED
    assert service.has_unresolved_intents("LBPT10087357", exclude_action_intent_id=parent.intent.id) is False

    replayed = service.submit_order(
        request,
        idempotency_key="child-key",
        action_context=context,
        parent_action_intent_id=parent.intent.id,
    )
    assert replayed.id == order.id
    assert replayed.idempotent_replayed is True


def test_fake_order_service_keeps_unknown_parent_state_explicit() -> None:
    service = FakeOrderService()
    prepared = service.prepare_trade_action(
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        idempotency_key="unknown-parent",
        request_hash="unknown-hash",
        action_context=TradingActionContext(action="bull_put_scan"),
        request_payload={},
    )

    service.mark_trade_action_unknown(prepared.intent.id, "simulated broker outcome unknown")

    assert service.get_trade_action(prepared.intent.id).state == TradingIntentState.UNKNOWN
