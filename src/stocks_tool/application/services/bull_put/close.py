from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from stocks_tool.application.services.bull_put.execution import BullPutExecutionSupport
from stocks_tool.application.services.strategy_idempotency import strategy_order_identity
from stocks_tool.domain.enums import OrderSide, OrderStatus, OrderType, SpreadStatus
from stocks_tool.domain.models import (
    BullPutSpread,
    OptionMarketSnapshot,
    Order,
    RecoverBullPutCloseRequest,
)


class MarkManualActionRequired(Protocol):
    def __call__(
        self,
        spread: BullPutSpread,
        *,
        reason: str,
        detail: str,
        intent_id: str | None = None,
        linked_order_field: str | None = None,
        linked_order_id: str | None = None,
    ) -> BullPutSpread: ...


class ValidateRecoverCloseRequest(Protocol):
    def __call__(self, *, spread: BullPutSpread, request: RecoverBullPutCloseRequest) -> None: ...


class RejectRecoverClose(Protocol):
    def __call__(
        self,
        *,
        spread: BullPutSpread,
        request: RecoverBullPutCloseRequest,
        warning_code: str,
        detail: str,
        order_ids: list[str] | None = None,
    ) -> None: ...


class AppendRecoverCloseAuditEvent(Protocol):
    def __call__(
        self,
        *,
        spread: BullPutSpread,
        request: RecoverBullPutCloseRequest,
        action: str,
        order_ids: list[str],
        before: dict | None,
        after: dict | None,
        summary: str,
        warning_code: str | None = None,
    ) -> None: ...


class BullPutCloseOrchestrator:
    """Close and manually recover Bull Put spreads using shared execution support."""

    def __init__(
        self,
        *,
        execution: BullPutExecutionSupport,
        mark_manual_action_required: MarkManualActionRequired,
        validate_recover_close_request: ValidateRecoverCloseRequest,
        reject_recover_close: RejectRecoverClose,
        append_recover_close_audit_event: AppendRecoverCloseAuditEvent,
    ) -> None:
        self.execution = execution
        self.mark_manual_action_required = mark_manual_action_required
        self.validate_recover_close_request = validate_recover_close_request
        self.reject_recover_close = reject_recover_close
        self.append_recover_close_audit_event = append_recover_close_audit_event

    def close_after_monitor(
        self,
        *,
        spread: BullPutSpread,
        reason: str,
        short_leg: OptionMarketSnapshot,
        long_leg: OptionMarketSnapshot,
        request_namespace: str | None = None,
        parent_action_intent_id: str | None = None,
    ) -> BullPutSpread:
        idempotency_key, action_context = strategy_order_identity(
            strategy_id=spread.strategy_id,
            entity_id=spread.id,
            action="bull_put_exit",
            leg="short_exit",
        )
        short_exit_order = self.execution.orders.submit_order(
            self.execution.build_leg_order_request(
                external_account_id=spread.external_account_id,
                leg=short_leg,
                side=OrderSide.BUY,
                quantity=spread.contracts,
                mode=spread.mode,
                order_type=OrderType.LIMIT,
                limit_price=short_leg.ask,
                remark=reason,
            ),
            idempotency_key=idempotency_key,
            action_context=action_context,
            parent_action_intent_id=parent_action_intent_id,
        )
        spread = self.execution.update_spread(
            spread,
            status=SpreadStatus.EXIT_PENDING_SHORT,
            short_exit_order_id=short_exit_order.id,
            exit_reason=reason,
            updated_at=datetime.now(timezone.utc),
        )
        short_exit_order = self.execution.await_terminal_or_fill(short_exit_order)
        if not self.execution.is_filled(short_exit_order):
            canceled = self.execution.cancel_if_working(
                short_exit_order,
                parent_action_intent_id=parent_action_intent_id,
                parent_entity_id=spread.id,
            ) or short_exit_order
            if (
                canceled.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}
                and canceled.executed_quantity == 0
            ):
                return self.execution.update_spread(
                    spread,
                    status=SpreadStatus.OPEN,
                    last_synced_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            return self.mark_manual_action_required(
                spread,
                reason="short_exit_cancel_not_final",
                detail=(
                    f"Short exit order {canceled.id} is not confirmed canceled with zero fills; "
                    "the spread remains exit-pending."
                ),
            )

        return self.close_long_leg(
            spread,
            reason=reason,
            leg=long_leg,
            request_namespace=request_namespace,
            parent_action_intent_id=parent_action_intent_id,
        )

    def close_long_leg(
        self,
        spread: BullPutSpread,
        *,
        reason: str,
        leg: OptionMarketSnapshot | None = None,
        request_namespace: str | None = None,
        parent_action_intent_id: str | None = None,
    ) -> BullPutSpread:
        del request_namespace
        long_leg = leg or self.execution.build_spread_leg_snapshot(
            spread,
            symbol=spread.long_symbol,
            strike=spread.long_strike,
        )
        idempotency_key, action_context = strategy_order_identity(
            strategy_id=spread.strategy_id,
            entity_id=spread.id,
            action="bull_put_exit",
            leg="long_exit",
        )
        long_exit_order = self.execution.orders.submit_order(
            self.execution.build_leg_order_request(
                external_account_id=spread.external_account_id,
                leg=long_leg,
                side=OrderSide.SELL,
                quantity=spread.contracts,
                mode=spread.mode,
                order_type=OrderType.MARKET,
                limit_price=None,
                remark=reason,
            ),
            idempotency_key=idempotency_key,
            action_context=action_context,
            parent_action_intent_id=parent_action_intent_id,
        )
        spread = self.execution.update_spread(
            spread,
            status=SpreadStatus.EXIT_PENDING_LONG,
            long_exit_order_id=long_exit_order.id,
            exit_reason=reason,
            updated_at=datetime.now(timezone.utc),
        )
        long_exit_order = self.execution.await_terminal_or_fill(long_exit_order)
        if self.execution.is_filled(long_exit_order):
            return self.execution.update_spread(
                spread,
                status=SpreadStatus.CLOSED,
                closed_at=datetime.now(timezone.utc),
                last_synced_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        canceled = self.execution.cancel_if_working(long_exit_order) or long_exit_order
        pending = self.execution.update_spread(
            spread,
            status=SpreadStatus.EXIT_PENDING_LONG,
            last_synced_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        if canceled.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}:
            return self.mark_manual_action_required(
                pending,
                reason="long_exit_unfilled",
                detail=f"Long exit order {canceled.id} ended without a full fill; manual action is required.",
            )
        return self.mark_manual_action_required(
            pending,
            reason="long_exit_cancel_not_final",
            detail=f"Long exit order {canceled.id} cancellation is not final; do not submit another exit order.",
        )

    def recover_close(
        self,
        *,
        spread: BullPutSpread,
        request: RecoverBullPutCloseRequest,
        idempotency_key: str | None,
        parent_action_intent_id: str | None,
        on_broker_phase_started: Callable[[], None],
    ) -> BullPutSpread:
        self.validate_recover_close_request(spread=spread, request=request)
        if spread.short_exit_order_id is None:
            self.reject_recover_close(
                spread=spread,
                request=request,
                warning_code="missing_short_close_order",
                detail="Bull put close recovery requires an existing short close order.",
            )
        short_exit_order = self.execution.orders.refresh_order(spread.short_exit_order_id)
        if self.execution.is_working(short_exit_order):
            self.reject_recover_close(
                spread=spread,
                request=request,
                warning_code="working_replacement_exists",
                detail="Bull put close recovery is blocked because the existing short close order is still working.",
                order_ids=[short_exit_order.id],
            )
        if not self.execution.is_failed_or_expired_close_order(spread=spread, order=short_exit_order):
            self.reject_recover_close(
                spread=spread,
                request=request,
                warning_code="short_close_order_not_failed",
                detail="Bull put close recovery requires the previous short close order to be canceled, rejected, or expired.",
                order_ids=[short_exit_order.id],
            )

        short_leg, long_leg = self.execution.load_spread_leg_quotes(spread)
        if short_leg.ask is None:
            self.reject_recover_close(
                spread=spread,
                request=request,
                warning_code="missing_replacement_ask",
                detail=f"Could not recover close because {short_leg.symbol} has no ask price.",
                order_ids=[short_exit_order.id],
            )
        if request.max_debit is not None and short_leg.ask > request.max_debit:
            self.reject_recover_close(
                spread=spread,
                request=request,
                warning_code="max_debit_exceeded",
                detail=f"Replacement close ask {short_leg.ask} exceeds max_debit {request.max_debit}.",
                order_ids=[short_exit_order.id],
            )

        reason = request.note or "manual_recover_close"
        child_idempotency_key, action_context = strategy_order_identity(
            strategy_id=spread.strategy_id,
            entity_id=spread.id,
            action="bull_put_recover_close",
            leg=f"short_exit_after:{short_exit_order.id}",
        )
        on_broker_phase_started()
        replacement_order = self.execution.orders.submit_order(
            self.execution.build_leg_order_request(
                external_account_id=spread.external_account_id,
                leg=short_leg,
                side=OrderSide.BUY,
                quantity=spread.contracts,
                mode=spread.mode,
                order_type=OrderType.LIMIT,
                limit_price=short_leg.ask,
                remark=reason,
            ),
            idempotency_key=child_idempotency_key,
            action_context=action_context,
            parent_action_intent_id=parent_action_intent_id,
        )
        spread = self.execution.update_spread(
            spread,
            status=SpreadStatus.EXIT_PENDING_SHORT,
            short_exit_order_id=replacement_order.id,
            exit_reason=spread.exit_reason or "manual_recover_close",
            lifecycle_warning_code=None,
            manual_action_required=False,
            latest_close_order_status=replacement_order.status.value,
            updated_at=datetime.now(timezone.utc),
        )
        self.append_recover_close_audit_event(
            spread=spread,
            request=request,
            action="bull_put_recover_close_submitted",
            order_ids=[short_exit_order.id, replacement_order.id],
            before={
                "status": SpreadStatus.OPEN.value,
                "short_exit_order_id": short_exit_order.id,
                "short_exit_order_status": short_exit_order.status.value,
            },
            after={
                "status": spread.status.value,
                "short_exit_order_id": replacement_order.id,
                "limit_price": str(short_leg.ask),
            },
            summary="Manual bull put close recovery submitted a replacement buy-to-close order.",
        )

        replacement_order = self.execution.await_terminal_or_fill(replacement_order)
        if not self.execution.is_filled(replacement_order):
            final_order = self.execution.cancel_if_working(
                replacement_order,
                parent_action_intent_id=parent_action_intent_id,
                parent_entity_id=spread.id,
            ) or replacement_order
            lifecycle_payload = self.execution.lifecycle_payload_for_close_order_state(
                spread=spread,
                status=SpreadStatus.EXIT_PENDING_SHORT,
                short_exit_order=final_order,
            )
            if (
                final_order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}
                and final_order.executed_quantity == 0
            ):
                return self.execution.update_spread(
                    spread,
                    status=SpreadStatus.OPEN,
                    latest_close_order_status=final_order.status.value,
                    lifecycle_warning_code="close_order_canceled_manual_action_needed",
                    manual_action_required=True,
                    raw_payload=lifecycle_payload,
                    last_synced_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            return self.execution.update_spread(
                spread,
                status=SpreadStatus.EXIT_PENDING_SHORT,
                latest_close_order_status=final_order.status.value,
                lifecycle_warning_code="short_exit_cancel_not_final",
                manual_action_required=True,
                raw_payload=lifecycle_payload,
                last_synced_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        closed = self.close_long_leg(
            spread,
            reason=reason,
            leg=long_leg,
            request_namespace=idempotency_key,
            parent_action_intent_id=parent_action_intent_id,
        )
        self.append_recover_close_audit_event(
            spread=closed,
            request=request,
            action="bull_put_recover_close_completed",
            order_ids=[replacement_order.id, closed.long_exit_order_id]
            if closed.long_exit_order_id
            else [replacement_order.id],
            before={"status": spread.status.value},
            after={"status": closed.status.value},
            summary="Manual bull put close recovery filled the replacement short close order.",
        )
        return closed
