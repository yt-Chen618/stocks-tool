from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
)
from stocks_tool.application.services.bull_put.candidate import (
    entry_long_limit_price as compute_entry_long_limit_price,
    entry_long_price_ladder as compute_entry_long_price_ladder,
    entry_short_price_ladder as compute_entry_short_price_ladder,
)
from stocks_tool.application.services.orders import (
    OrderService,
    TradingIntentOutcomeUnknownError,
    TradingIntentRejectedError,
)
from stocks_tool.application.services.strategy_idempotency import strategy_order_identity
from stocks_tool.core.config import BullPutSpreadStrategySettings
from stocks_tool.domain.enums import (
    BrokerName,
    ExecutionMode,
    OrderSide,
    OrderStatus,
    OrderType,
    SpreadStatus,
)
from stocks_tool.domain.models import (
    BullPutSpread,
    BullPutSpreadScanResult,
    BullPutStrategyRuntimeState,
    CreateOrderRequest,
    ExecuteBullPutSpreadRequest,
    OptionMarketSnapshot,
    Order,
)
from stocks_tool.ports.repository import BullPutSpreadRepository


class BullPutManualActionRequiredError(RuntimeError):
    """Raised when an entry leg may still be working or has a residual fill."""


class BullPutLegPersistenceError(RuntimeError):
    """Carries a broker-acknowledged leg when linking it to the spread failed."""

    def __init__(self, *, order: Order, order_id_field: str, cause: Exception) -> None:
        super().__init__(f"Could not link broker order {order.id} to {order_id_field}: {cause}")
        self.order = order
        self.order_id_field = order_id_field


class SpreadUpdater(Protocol):
    def __call__(self, spread: BullPutSpread, **updates: object) -> BullPutSpread: ...


class EntryLegRequestBuilder(Protocol):
    def __call__(
        self,
        *,
        external_account_id: str,
        leg: OptionMarketSnapshot,
        side: OrderSide,
        quantity: int,
        mode: ExecutionMode,
        order_type: OrderType,
        limit_price: Decimal | None,
        remark: str | None,
    ) -> CreateOrderRequest: ...


class TopOfBookLoader(Protocol):
    def __call__(self, quote: OptionMarketSnapshot, *, mode: ExecutionMode) -> OptionMarketSnapshot: ...


class AwaitTerminalOrFill(Protocol):
    def __call__(self, order: Order) -> Order: ...


class CancelWorkingOrder(Protocol):
    def __call__(
        self,
        order: Order,
        *,
        parent_action_intent_id: str | None = None,
        parent_entity_id: str | None = None,
    ) -> Order | None: ...


class BuildSpreadLegSnapshot(Protocol):
    def __call__(self, spread: BullPutSpread, *, symbol: str, strike: Decimal) -> OptionMarketSnapshot: ...


class EffectiveFillPrice(Protocol):
    def __call__(self, order: Order | None) -> Decimal | None: ...


class ActualEntryRiskUpdates(Protocol):
    def __call__(self, *, spread: BullPutSpread, entry_net_credit: Decimal | None) -> dict[str, object]: ...


class IsFilled(Protocol):
    def __call__(self, order: Order | None) -> bool: ...


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


class LogEntryFailure(Protocol):
    def __call__(self, spread: BullPutSpread, *, reason: str) -> BullPutSpread: ...


class RecordOpenedSpread(Protocol):
    def __call__(
        self,
        spread: BullPutSpread,
        *,
        preview: BullPutSpreadScanResult,
        runtime_state: BullPutStrategyRuntimeState,
        as_of: datetime,
    ) -> BullPutSpread: ...


class PrepareRuntimeState(Protocol):
    def __call__(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        as_of: datetime,
    ) -> BullPutStrategyRuntimeState: ...


class LockForEntry(Protocol):
    def __call__(
        self,
        *,
        external_account_id: str,
        strategy_id: str,
    ) -> BullPutStrategyRuntimeState | None: ...


class AssertEntryCapacity(Protocol):
    def __call__(
        self,
        *,
        external_account_id: str,
        symbol: str,
        runtime_state: BullPutStrategyRuntimeState,
    ) -> None: ...


class EntrySessionGateReason(Protocol):
    def __call__(self, as_of: datetime) -> str | None: ...


class BullPutEntryOrchestrator:
    """Open a Bull Put spread after the facade has prepared its public action."""

    def __init__(
        self,
        *,
        strategy_settings: BullPutSpreadStrategySettings,
        order_service: OrderService,
        spreads: BullPutSpreadRepository,
        update_spread: SpreadUpdater,
        build_leg_order_request: EntryLegRequestBuilder,
        with_top_of_book: TopOfBookLoader,
        await_terminal_or_fill: AwaitTerminalOrFill,
        cancel_if_working: CancelWorkingOrder,
        build_spread_leg_snapshot: BuildSpreadLegSnapshot,
        effective_fill_price: EffectiveFillPrice,
        actual_entry_risk_updates: ActualEntryRiskUpdates,
        is_filled: IsFilled,
        mark_manual_action_required: MarkManualActionRequired,
        log_entry_failure: LogEntryFailure,
        record_opened_spread: RecordOpenedSpread,
        prepare_runtime_state: PrepareRuntimeState,
        lock_for_entry: LockForEntry,
        assert_entry_capacity: AssertEntryCapacity,
        entry_session_gate_reason: EntrySessionGateReason,
    ) -> None:
        self.strategy_settings = strategy_settings
        self.order_service = order_service
        self.spreads = spreads
        self.update_spread = update_spread
        self.build_leg_order_request = build_leg_order_request
        self.with_top_of_book = with_top_of_book
        self.await_terminal_or_fill = await_terminal_or_fill
        self.cancel_if_working = cancel_if_working
        self.build_spread_leg_snapshot = build_spread_leg_snapshot
        self.effective_fill_price = effective_fill_price
        self.actual_entry_risk_updates = actual_entry_risk_updates
        self.is_filled = is_filled
        self.mark_manual_action_required = mark_manual_action_required
        self.log_entry_failure = log_entry_failure
        self.record_opened_spread = record_opened_spread
        self.prepare_runtime_state = prepare_runtime_state
        self.lock_for_entry = lock_for_entry
        self.assert_entry_capacity = assert_entry_capacity
        self.entry_session_gate_reason = entry_session_gate_reason

    def open_from_preview(
        self,
        *,
        request: ExecuteBullPutSpreadRequest,
        preview: BullPutSpreadScanResult,
        action_spread_id: str | None = None,
        action_request_hash: str | None = None,
        parent_action_intent_id: str | None = None,
        on_broker_phase_started: Callable[[], None] | None = None,
    ) -> BullPutSpread:
        if not preview.eligible or preview.candidate is None or preview.risk is None:
            failure_reason = (
                preview.reasons[0]
                if preview.reasons
                else "Bull put spread preview did not produce an eligible candidate."
            )
            raise ValueError(failure_reason)
        session_reason = self.entry_session_gate_reason(preview.scanned_at)
        if session_reason is not None:
            raise ValueError(session_reason)

        runtime_state = self.prepare_runtime_state(
            external_account_id=request.external_account_id,
            mode=request.mode,
            as_of=preview.scanned_at,
        )
        locked_runtime_state = self.lock_for_entry(
            external_account_id=request.external_account_id,
            strategy_id=runtime_state.strategy_id,
        )
        if locked_runtime_state is None:
            raise ValueError("Bull put runtime state disappeared before entry capacity could be reserved.")
        runtime_state = locked_runtime_state
        self.assert_entry_capacity(
            external_account_id=request.external_account_id,
            symbol=request.symbol,
            runtime_state=runtime_state,
        )

        now = preview.scanned_at
        spread = BullPutSpread(
            **({"id": action_spread_id} if action_spread_id is not None else {}),
            broker=BrokerName.LONGBRIDGE,
            external_account_id=request.external_account_id,
            mode=request.mode,
            underlying_symbol=request.symbol,
            expiration_date=preview.candidate.expiration_date,
            contracts=self.strategy_settings.contracts_per_trade,
            width=preview.candidate.width,
            long_symbol=preview.candidate.long_put.symbol,
            long_strike=preview.candidate.long_put.strike,
            short_symbol=preview.candidate.short_put.symbol,
            short_strike=preview.candidate.short_put.strike,
            status=SpreadStatus.ENTRY_PENDING_LONG,
            max_profit=preview.risk.max_profit,
            max_loss=preview.risk.max_loss,
            break_even=preview.risk.break_even,
            account_risk_pct=preview.risk.account_risk_pct,
            raw_payload={
                "preview": preview.model_dump(mode="json"),
                "action_request_hash": action_request_hash,
            },
            entry_started_at=now,
            created_at=now,
            updated_at=now,
        )
        spread = self.spreads.create_spread(spread)
        entry_long_leg = self.with_top_of_book(preview.candidate.long_put, mode=request.mode)
        entry_short_leg = self.with_top_of_book(preview.candidate.short_put, mode=request.mode)
        long_entry_cap = self._entry_long_limit_price(
            long_leg=entry_long_leg,
            short_leg=entry_short_leg,
            width=preview.candidate.width,
        )
        if on_broker_phase_started is not None:
            on_broker_phase_started()
        try:
            spread, long_entry_order = self._submit_entry_leg_with_repricing(
                spread=spread,
                external_account_id=request.external_account_id,
                leg=entry_long_leg,
                side=OrderSide.BUY,
                quantity=spread.contracts,
                mode=request.mode,
                remark=request.remark,
                price_ladder=self._entry_long_price_ladder(
                    ask_price=entry_long_leg.ask,
                    capped_price=long_entry_cap,
                ),
                order_id_field="long_entry_order_id",
                parent_action_intent_id=parent_action_intent_id,
            )
        except BullPutLegPersistenceError as exc:
            return self.mark_manual_action_required(
                spread,
                reason="long_entry_link_failed",
                detail=str(exc),
                linked_order_field=exc.order_id_field,
                linked_order_id=exc.order.id,
            )
        except BullPutManualActionRequiredError as exc:
            return self.mark_manual_action_required(
                spread,
                reason="long_entry_outcome_unknown",
                detail=str(exc),
            )
        except TradingIntentOutcomeUnknownError as exc:
            self.mark_manual_action_required(
                spread,
                reason="long_entry_outcome_unknown",
                detail=str(exc),
                intent_id=exc.intent_id,
            )
            raise
        except (
            TradingIntentRejectedError,
            LongbridgeConfigurationError,
            LongbridgeDependencyError,
        ):
            failed = self.update_spread(
                spread,
                status=SpreadStatus.ENTRY_FAILED,
                exit_reason="long_entry_rejected",
                last_synced_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            return self.log_entry_failure(failed, reason="long_entry_rejected")
        except Exception as exc:
            self.mark_manual_action_required(
                spread,
                reason="long_entry_outcome_unknown",
                detail=str(exc),
            )
            raise
        if not self.is_filled(long_entry_order):
            failed = self.update_spread(
                spread,
                status=SpreadStatus.ENTRY_FAILED,
                exit_reason="long_entry_unfilled",
                last_synced_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            return self.log_entry_failure(failed, reason="long_entry_unfilled")

        spread = self.update_spread(
            spread,
            status=SpreadStatus.ENTRY_PENDING_SHORT,
            entry_long_price=self.effective_fill_price(long_entry_order),
            last_synced_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        try:
            spread, short_entry_order = self._submit_entry_leg_with_repricing(
                spread=spread,
                external_account_id=request.external_account_id,
                leg=entry_short_leg,
                side=OrderSide.SELL,
                quantity=spread.contracts,
                mode=request.mode,
                remark=request.remark,
                price_ladder=self._entry_short_price_ladder(
                    bid_price=entry_short_leg.bid,
                    filled_long_price=self.effective_fill_price(long_entry_order),
                    width=preview.candidate.width,
                ),
                order_id_field="short_entry_order_id",
                parent_action_intent_id=parent_action_intent_id,
            )
        except BullPutLegPersistenceError as exc:
            return self.mark_manual_action_required(
                spread,
                reason="short_entry_link_failed",
                detail=str(exc),
                linked_order_field=exc.order_id_field,
                linked_order_id=exc.order.id,
            )
        except (
            TradingIntentRejectedError,
            LongbridgeConfigurationError,
            LongbridgeDependencyError,
        ):
            rolled_back = self._rollback_long_leg(
                spread,
                reason="short_entry_submit_failed",
                parent_action_intent_id=parent_action_intent_id,
            )
            return self.log_entry_failure(rolled_back, reason="short_entry_submit_failed")
        except BullPutManualActionRequiredError as exc:
            return self.mark_manual_action_required(
                spread,
                reason="short_entry_outcome_unknown",
                detail=str(exc),
            )
        except TradingIntentOutcomeUnknownError as exc:
            self.mark_manual_action_required(
                spread,
                reason="short_entry_outcome_unknown",
                detail=str(exc),
                intent_id=exc.intent_id,
            )
            raise
        except Exception as exc:
            self.mark_manual_action_required(
                spread,
                reason="short_entry_outcome_unknown",
                detail=str(exc),
            )
            raise
        if not self.is_filled(short_entry_order):
            rolled_back = self._rollback_long_leg(
                spread,
                reason="short_entry_unfilled",
                parent_action_intent_id=parent_action_intent_id,
            )
            return self.log_entry_failure(rolled_back, reason="short_entry_unfilled")

        entry_long_price = self.effective_fill_price(long_entry_order)
        entry_short_price = self.effective_fill_price(short_entry_order)
        entry_net_credit = None
        if entry_long_price is not None and entry_short_price is not None:
            entry_net_credit = entry_short_price - entry_long_price
        opened = self.update_spread(
            spread,
            status=SpreadStatus.OPEN,
            entry_long_price=entry_long_price,
            entry_short_price=entry_short_price,
            entry_net_credit=entry_net_credit,
            **self.actual_entry_risk_updates(
                spread=spread,
                entry_net_credit=entry_net_credit,
            ),
            opened_at=datetime.now(timezone.utc),
            last_synced_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        return self.record_opened_spread(
            opened,
            preview=preview,
            runtime_state=runtime_state,
            as_of=now,
        )

    def _submit_entry_leg_with_repricing(
        self,
        *,
        spread: BullPutSpread,
        external_account_id: str,
        leg: OptionMarketSnapshot,
        side: OrderSide,
        quantity: int,
        mode: ExecutionMode,
        remark: str | None,
        price_ladder: list[Decimal | None],
        order_id_field: str,
        parent_action_intent_id: str | None,
    ) -> tuple[BullPutSpread, Order]:
        if not price_ladder:
            raise ValueError(f"No valid repricing ladder was available for {leg.symbol}.")
        last_order: Order | None = None
        leg_name = order_id_field.removesuffix("_order_id")
        for attempt, limit_price in enumerate(price_ladder):
            idempotency_key, action_context = strategy_order_identity(
                strategy_id=spread.strategy_id,
                entity_id=spread.id,
                action="bull_put_entry",
                leg=leg_name,
                attempt=attempt,
            )
            submitted = self.order_service.submit_order(
                self.build_leg_order_request(
                    external_account_id=external_account_id,
                    leg=leg,
                    side=side,
                    quantity=quantity,
                    mode=mode,
                    order_type=OrderType.LIMIT,
                    limit_price=limit_price,
                    remark=remark,
                ),
                idempotency_key=idempotency_key,
                action_context=action_context,
                parent_action_intent_id=parent_action_intent_id,
            )
            try:
                spread = self.update_spread(
                    spread,
                    **{
                        order_id_field: submitted.id,
                        "updated_at": datetime.now(timezone.utc),
                    },
                )
            except Exception as exc:
                raise BullPutLegPersistenceError(
                    order=submitted,
                    order_id_field=order_id_field,
                    cause=exc,
                ) from exc
            current = self.await_terminal_or_fill(submitted)
            if self.is_filled(current):
                return spread, current
            last_order = self.cancel_if_working(
                current,
                parent_action_intent_id=parent_action_intent_id,
                parent_entity_id=spread.id,
            ) or current
            if last_order.executed_quantity > 0:
                raise BullPutManualActionRequiredError(
                    f"{leg_name} order {last_order.id} has a residual fill; no repricing order was submitted."
                )
            if last_order.status not in {OrderStatus.CANCELED, OrderStatus.REJECTED}:
                raise BullPutManualActionRequiredError(
                    f"{leg_name} order {last_order.id} cancellation is not final; no repricing order was submitted."
                )
        if last_order is None:
            raise ValueError(f"Unable to submit any repricing attempt for {leg.symbol}.")
        return spread, last_order

    def _rollback_long_leg(
        self,
        spread: BullPutSpread,
        *,
        reason: str,
        parent_action_intent_id: str | None,
    ) -> BullPutSpread:
        rollback_leg = self.build_spread_leg_snapshot(
            spread,
            symbol=spread.long_symbol,
            strike=spread.long_strike,
        )
        try:
            idempotency_key, action_context = strategy_order_identity(
                strategy_id=spread.strategy_id,
                entity_id=spread.id,
                action="bull_put_rollback",
                leg="long_exit",
            )
            rollback_order = self.order_service.submit_order(
                self.build_leg_order_request(
                    external_account_id=spread.external_account_id,
                    leg=rollback_leg,
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
        except Exception as exc:
            failed = self.update_spread(
                spread,
                status=SpreadStatus.ROLLBACK_FAILED,
                exit_reason=reason,
                last_synced_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            return self.mark_manual_action_required(
                failed,
                reason="rollback_order_outcome_unknown",
                detail=str(exc),
            )

        spread = self.update_spread(
            spread,
            long_exit_order_id=rollback_order.id,
            exit_reason=reason,
            updated_at=datetime.now(timezone.utc),
        )
        rollback_order = self.await_terminal_or_fill(rollback_order)
        if self.is_filled(rollback_order):
            return self.update_spread(
                spread,
                status=SpreadStatus.ROLLED_BACK,
                closed_at=datetime.now(timezone.utc),
                last_synced_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        failed = self.update_spread(
            spread,
            status=SpreadStatus.ROLLBACK_FAILED,
            last_synced_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        return self.mark_manual_action_required(
            failed,
            reason="rollback_order_unfilled",
            detail=f"Rollback order {rollback_order.id} did not fill; retain manual control of the residual long leg.",
        )

    def _entry_long_limit_price(
        self,
        *,
        long_leg: OptionMarketSnapshot,
        short_leg: OptionMarketSnapshot,
        width: Decimal,
    ) -> Decimal | None:
        return compute_entry_long_limit_price(
            long_leg=long_leg,
            short_leg=short_leg,
            width=width,
            entry_long_limit_buffer=self.strategy_settings.entry_long_limit_buffer,
            min_conservative_credit_per_width_ratio=self.strategy_settings.min_conservative_credit_per_width_ratio,
        )

    def _entry_long_price_ladder(
        self,
        *,
        ask_price: Decimal | None,
        capped_price: Decimal | None,
    ) -> list[Decimal | None]:
        return compute_entry_long_price_ladder(
            ask_price=ask_price,
            capped_price=capped_price,
            entry_reprice_increment=self.strategy_settings.entry_reprice_increment,
            entry_reprice_max_steps=self.strategy_settings.entry_reprice_max_steps,
        )

    def _entry_short_price_ladder(
        self,
        *,
        bid_price: Decimal | None,
        filled_long_price: Decimal | None,
        width: Decimal,
    ) -> list[Decimal | None]:
        return compute_entry_short_price_ladder(
            bid_price=bid_price,
            filled_long_price=filled_long_price,
            width=width,
            entry_reprice_increment=self.strategy_settings.entry_reprice_increment,
            entry_reprice_max_steps=self.strategy_settings.entry_reprice_max_steps,
            min_conservative_credit_per_width_ratio=self.strategy_settings.min_conservative_credit_per_width_ratio,
        )
