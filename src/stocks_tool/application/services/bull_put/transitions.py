from __future__ import annotations

from dataclasses import dataclass

from stocks_tool.domain.enums import OrderStatus, SpreadStatus


@dataclass(frozen=True)
class BullPutOrderState:
    status: OrderStatus | None = None
    executed_quantity: int = 0


@dataclass(frozen=True)
class BullPutTransition:
    status: SpreadStatus
    manual_action_required: bool = False
    warning_code: str | None = None


def _is_filled(state: BullPutOrderState) -> bool:
    return state.status == OrderStatus.FILLED


def _manual_transition(current_status: SpreadStatus) -> BullPutTransition:
    return BullPutTransition(
        status=current_status,
        manual_action_required=True,
        warning_code="bull_put_residual_position_requires_manual_action",
    )


def evaluate_bull_put_transition(
    *,
    current_status: SpreadStatus,
    long_entry: BullPutOrderState,
    short_entry: BullPutOrderState,
    short_exit: BullPutOrderState,
    long_exit: BullPutOrderState,
) -> BullPutTransition:
    if current_status == SpreadStatus.ROLLED_BACK and (
        short_entry.executed_quantity > short_exit.executed_quantity
        or long_entry.executed_quantity > long_exit.executed_quantity
    ):
        return _manual_transition(current_status)
    if current_status == SpreadStatus.CLOSED and (
        short_entry.executed_quantity > short_exit.executed_quantity
        or long_entry.executed_quantity > long_exit.executed_quantity
    ):
        return _manual_transition(current_status)
    if (
        current_status == SpreadStatus.ENTRY_PENDING_LONG
        and long_entry.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}
        and long_entry.executed_quantity == 0
    ):
        return BullPutTransition(status=SpreadStatus.ENTRY_FAILED)
    if current_status == SpreadStatus.ENTRY_PENDING_LONG and _is_filled(long_entry):
        return BullPutTransition(status=SpreadStatus.ENTRY_PENDING_SHORT)
    if (
        current_status == SpreadStatus.ENTRY_PENDING_SHORT
        and _is_filled(long_entry)
        and _is_filled(short_entry)
    ):
        return BullPutTransition(status=SpreadStatus.OPEN)
    if (
        current_status == SpreadStatus.ENTRY_PENDING_SHORT
        and short_entry.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}
        and _is_filled(long_exit)
    ):
        return BullPutTransition(status=SpreadStatus.ROLLED_BACK)
    if (
        current_status == SpreadStatus.ENTRY_PENDING_SHORT
        and short_entry.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}
    ):
        return BullPutTransition(
            status=SpreadStatus.ROLLBACK_FAILED,
            manual_action_required=True,
            warning_code="bull_put_residual_position_requires_manual_action",
        )
    if current_status == SpreadStatus.ENTRY_FAILED and (
        long_entry.executed_quantity > 0 or short_entry.executed_quantity > 0
    ):
        return BullPutTransition(
            status=current_status,
            manual_action_required=True,
            warning_code="bull_put_late_fill_requires_manual_action",
        )
    if current_status == SpreadStatus.ROLLBACK_FAILED and _is_filled(long_exit):
        return BullPutTransition(status=SpreadStatus.ROLLED_BACK)
    if current_status == SpreadStatus.EXIT_PENDING_SHORT and _is_filled(short_exit):
        return BullPutTransition(status=SpreadStatus.EXIT_PENDING_LONG)
    if (
        current_status == SpreadStatus.EXIT_PENDING_SHORT
        and short_exit.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}
        and short_exit.executed_quantity > 0
    ):
        return BullPutTransition(
            status=current_status,
            manual_action_required=True,
            warning_code="bull_put_residual_position_requires_manual_action",
        )
    if (
        current_status == SpreadStatus.EXIT_PENDING_SHORT
        and short_exit.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}
    ):
        return BullPutTransition(status=SpreadStatus.OPEN)
    if current_status == SpreadStatus.EXIT_PENDING_LONG and _is_filled(long_exit):
        return BullPutTransition(status=SpreadStatus.CLOSED)
    if (
        current_status == SpreadStatus.EXIT_PENDING_LONG
        and long_exit.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}
    ):
        return _manual_transition(current_status)
    if current_status == SpreadStatus.EXIT_PENDING_LONG:
        return BullPutTransition(status=SpreadStatus.EXIT_PENDING_LONG)
    return BullPutTransition(status=current_status)
