from stocks_tool.application.services.bull_put.transitions import (
    BullPutOrderState,
    evaluate_bull_put_transition,
)
from stocks_tool.domain.enums import OrderStatus, SpreadStatus


def test_exit_pending_long_never_reopens_when_entry_orders_are_filled() -> None:
    transition = evaluate_bull_put_transition(
        current_status=SpreadStatus.EXIT_PENDING_LONG,
        long_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_exit=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        long_exit=BullPutOrderState(OrderStatus.SUBMITTED, executed_quantity=0),
    )

    assert transition.status == SpreadStatus.EXIT_PENDING_LONG


def test_terminal_entry_failure_with_late_fill_requires_manual_action() -> None:
    transition = evaluate_bull_put_transition(
        current_status=SpreadStatus.ENTRY_FAILED,
        long_entry=BullPutOrderState(OrderStatus.PARTIALLY_FILLED, executed_quantity=1),
        short_entry=BullPutOrderState(),
        short_exit=BullPutOrderState(),
        long_exit=BullPutOrderState(),
    )

    assert transition.status == SpreadStatus.ENTRY_FAILED
    assert transition.manual_action_required is True
    assert transition.warning_code == "bull_put_late_fill_requires_manual_action"


def test_partially_filled_canceled_short_exit_does_not_return_to_open() -> None:
    transition = evaluate_bull_put_transition(
        current_status=SpreadStatus.EXIT_PENDING_SHORT,
        long_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_exit=BullPutOrderState(OrderStatus.CANCELED, executed_quantity=1),
        long_exit=BullPutOrderState(),
    )

    assert transition.status == SpreadStatus.EXIT_PENDING_SHORT
    assert transition.manual_action_required is True


def test_zero_fill_canceled_short_exit_returns_to_open() -> None:
    transition = evaluate_bull_put_transition(
        current_status=SpreadStatus.EXIT_PENDING_SHORT,
        long_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_exit=BullPutOrderState(OrderStatus.CANCELED, executed_quantity=0),
        long_exit=BullPutOrderState(),
    )

    assert transition.status == SpreadStatus.OPEN
    assert transition.manual_action_required is False


def test_entry_pending_short_opens_only_after_both_legs_fill() -> None:
    transition = evaluate_bull_put_transition(
        current_status=SpreadStatus.ENTRY_PENDING_SHORT,
        long_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_exit=BullPutOrderState(),
        long_exit=BullPutOrderState(),
    )

    assert transition.status == SpreadStatus.OPEN


def test_entry_pending_long_rejection_without_fill_fails_entry() -> None:
    transition = evaluate_bull_put_transition(
        current_status=SpreadStatus.ENTRY_PENDING_LONG,
        long_entry=BullPutOrderState(OrderStatus.REJECTED, executed_quantity=0),
        short_entry=BullPutOrderState(),
        short_exit=BullPutOrderState(),
        long_exit=BullPutOrderState(),
    )

    assert transition.status == SpreadStatus.ENTRY_FAILED


def test_filled_long_entry_advances_to_short_entry() -> None:
    transition = evaluate_bull_put_transition(
        current_status=SpreadStatus.ENTRY_PENDING_LONG,
        long_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_entry=BullPutOrderState(),
        short_exit=BullPutOrderState(),
        long_exit=BullPutOrderState(),
    )

    assert transition.status == SpreadStatus.ENTRY_PENDING_SHORT


def test_rejected_short_entry_with_filled_rollback_is_rolled_back() -> None:
    transition = evaluate_bull_put_transition(
        current_status=SpreadStatus.ENTRY_PENDING_SHORT,
        long_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_entry=BullPutOrderState(OrderStatus.REJECTED, executed_quantity=0),
        short_exit=BullPutOrderState(),
        long_exit=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
    )

    assert transition.status == SpreadStatus.ROLLED_BACK


def test_rejected_short_entry_with_residual_long_leg_requires_manual_action() -> None:
    transition = evaluate_bull_put_transition(
        current_status=SpreadStatus.ENTRY_PENDING_SHORT,
        long_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_entry=BullPutOrderState(OrderStatus.REJECTED, executed_quantity=0),
        short_exit=BullPutOrderState(),
        long_exit=BullPutOrderState(OrderStatus.REJECTED, executed_quantity=0),
    )

    assert transition.status == SpreadStatus.ROLLBACK_FAILED
    assert transition.manual_action_required is True


def test_failed_rollback_closes_when_the_long_exit_eventually_fills() -> None:
    transition = evaluate_bull_put_transition(
        current_status=SpreadStatus.ROLLBACK_FAILED,
        long_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_entry=BullPutOrderState(OrderStatus.REJECTED, executed_quantity=0),
        short_exit=BullPutOrderState(),
        long_exit=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
    )

    assert transition.status == SpreadStatus.ROLLED_BACK
    assert transition.manual_action_required is False


def test_filled_short_exit_advances_to_long_exit() -> None:
    transition = evaluate_bull_put_transition(
        current_status=SpreadStatus.EXIT_PENDING_SHORT,
        long_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_exit=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        long_exit=BullPutOrderState(),
    )

    assert transition.status == SpreadStatus.EXIT_PENDING_LONG


def test_filled_long_exit_closes_spread() -> None:
    transition = evaluate_bull_put_transition(
        current_status=SpreadStatus.EXIT_PENDING_LONG,
        long_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_exit=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        long_exit=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
    )

    assert transition.status == SpreadStatus.CLOSED


def test_closed_spread_is_absorbing() -> None:
    transition = evaluate_bull_put_transition(
        current_status=SpreadStatus.CLOSED,
        long_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_exit=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        long_exit=BullPutOrderState(OrderStatus.SUBMITTED, executed_quantity=0),
    )

    assert transition.status == SpreadStatus.CLOSED


def test_rolled_back_spread_with_late_short_fill_requires_manual_action() -> None:
    transition = evaluate_bull_put_transition(
        current_status=SpreadStatus.ROLLED_BACK,
        long_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_entry=BullPutOrderState(OrderStatus.PARTIALLY_FILLED, executed_quantity=1),
        short_exit=BullPutOrderState(),
        long_exit=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
    )

    assert transition.status == SpreadStatus.ROLLED_BACK
    assert transition.manual_action_required is True


def test_rejected_long_exit_keeps_safe_state_and_requires_manual_action() -> None:
    transition = evaluate_bull_put_transition(
        current_status=SpreadStatus.EXIT_PENDING_LONG,
        long_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_entry=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        short_exit=BullPutOrderState(OrderStatus.FILLED, executed_quantity=1),
        long_exit=BullPutOrderState(OrderStatus.REJECTED, executed_quantity=0),
    )

    assert transition.status == SpreadStatus.EXIT_PENDING_LONG
    assert transition.manual_action_required is True
