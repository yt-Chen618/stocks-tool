from decimal import Decimal

from stocks_tool.domain.enums import ExecutionMode, OrderSide, OrderStatus
from stocks_tool.domain.models import ExecuteBullPutSpreadRequest

from tests.test_bull_put_strategy import (
    build_option_order,
    build_scan_time,
    build_service,
)


def test_entry_orchestrator_interface_preserves_two_leg_parent_and_child_identity() -> None:
    service, _, _, order_service = build_service()
    preview = service.preview_spread(
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        mode=ExecutionMode.PAPER,
        as_of=build_scan_time(),
    )
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="interface-long-entry",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
        ),
        build_option_order(
            order_id="interface-short-entry",
            symbol="QQQ260619P470000.US",
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            limit_price=Decimal("2.40"),
        ),
    ]

    spread = service.entry.open_from_preview(
        request=ExecuteBullPutSpreadRequest(
            external_account_id="LBPT10087357",
            symbol="QQQ.US",
            mode=ExecutionMode.PAPER,
            as_of=build_scan_time(),
        ),
        preview=preview,
        action_spread_id="interface-entry-spread",
        action_request_hash="interface-entry-request-hash",
        parent_action_intent_id="interface-parent-action",
    )

    assert spread.status.value == "open"
    assert spread.long_entry_order_id == "interface-long-entry"
    assert spread.short_entry_order_id == "interface-short-entry"
    assert [call.kwargs["parent_action_intent_id"] for call in order_service.submit_order.call_args_list] == [
        "interface-parent-action",
        "interface-parent-action",
    ]
    child_contexts = [call.kwargs["action_context"] for call in order_service.submit_order.call_args_list]
    assert [context.leg for context in child_contexts] == ["long_entry", "short_entry"]
    assert child_contexts[0].entity_id == spread.id
    assert child_contexts[1].entity_id == spread.id
    assert child_contexts[0].action == child_contexts[1].action == "bull_put_entry"
    assert child_contexts[0].strategy_id == child_contexts[1].strategy_id == "paper_bull_put_v1"
    assert order_service.submit_order.call_args_list[0].kwargs["idempotency_key"] != (
        order_service.submit_order.call_args_list[1].kwargs["idempotency_key"]
    )
