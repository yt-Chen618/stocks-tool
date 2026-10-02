from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stocks_tool.db.models import (
    BrokerAccountRecord,
    ExecutionRecord,
    OrderIntentRecord,
    OrderRecord,
    StrategyAuditEventRecord,
    TradeActionIntentRecord,
)
from stocks_tool.domain.enums import (
    BrokerName,
    ExecutionMode,
    TradingIntentState,
    TradingOperation,
)
from stocks_tool.domain.models import (
    BrokerOrderIntent,
    BrokerOrderSnapshot,
    CreateStrategyAuditEventRequest,
    Execution,
    Order,
    PreparedBrokerOrderIntent,
    PreparedTradeActionIntent,
    TradeActionIntent,
    TradingActionContext,
)
from stocks_tool.ports.trading_intent_ledger import (
    TradeActionIntentConflictError,
    TradingIntentLedger,
)
from stocks_tool.repositories.sqlalchemy_execution_repository import SQLAlchemyExecutionRepository
from stocks_tool.repositories.sqlalchemy_order_repository import SQLAlchemyOrderRepository
from stocks_tool.repositories.sqlalchemy_strategy_audit_event_repository import (
    SQLAlchemyStrategyAuditEventRepository,
)


UNRESOLVED_INTENT_STATES = {
    TradingIntentState.PREPARED.value,
    TradingIntentState.SUBMITTING.value,
    TradingIntentState.BROKER_ACKNOWLEDGED.value,
    TradingIntentState.UNKNOWN.value,
}


class SQLAlchemyTradingIntentLedger(TradingIntentLedger):
    """Owns transaction boundaries for broker mutation intent, order, fill summary, and audit."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def prepare_action(
        self,
        *,
        external_account_id: str,
        broker: BrokerName,
        mode: ExecutionMode,
        idempotency_key: str,
        request_hash: str,
        action_context: TradingActionContext,
        request_payload: dict,
    ) -> PreparedTradeActionIntent:
        existing = self._find_action_by_key(
            external_account_id=external_account_id,
            mode=mode,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            self._assert_action_replay_matches(
                existing,
                broker=broker,
                request_hash=request_hash,
                action_context=action_context,
            )
            return PreparedTradeActionIntent(
                intent=self._to_action_domain(existing),
                created=False,
            )

        action = TradeActionIntentRecord(
            id=str(uuid4()),
            broker_account_id=self._resolve_broker_account_id(external_account_id, broker),
            external_account_id=external_account_id,
            broker=broker.value,
            execution_mode=mode.value,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            action=action_context.action,
            strategy_id=action_context.strategy_id,
            entity_id=action_context.entity_id,
            state=TradingIntentState.PREPARED.value,
            request_payload=request_payload,
        )
        self.session.add(action)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self._find_action_by_key(
                external_account_id=external_account_id,
                mode=mode,
                idempotency_key=idempotency_key,
            )
            if concurrent is None:
                raise
            self._assert_action_replay_matches(
                concurrent,
                broker=broker,
                request_hash=request_hash,
                action_context=action_context,
            )
            return PreparedTradeActionIntent(
                intent=self._to_action_domain(concurrent),
                created=False,
            )
        self.session.refresh(action)
        return PreparedTradeActionIntent(
            intent=self._to_action_domain(action),
            created=True,
        )

    def mark_action_submitting(self, action_intent_id: str) -> TradeActionIntent:
        action = self._load_action_for_update(action_intent_id)
        if action.state in {
            TradingIntentState.PERSISTED.value,
            TradingIntentState.REJECTED.value,
            TradingIntentState.UNKNOWN.value,
            TradingIntentState.RESOLVED_NO_ORDER.value,
        }:
            return self._to_action_domain(action)
        action.state = TradingIntentState.SUBMITTING.value
        action.last_error = None
        self._commit()
        return self.get_action(action_intent_id) or self._to_action_domain(action)

    def complete_action(
        self,
        action_intent_id: str,
        response_payload: dict,
    ) -> TradeActionIntent:
        action = self._load_action_for_update(action_intent_id)
        if action.state == TradingIntentState.PERSISTED.value:
            if action.response_payload != response_payload:
                raise ValueError(
                    f"Trade action intent '{action.id}' is already complete with a different response."
                )
            return self._to_action_domain(action)
        if action.state in {
            TradingIntentState.REJECTED.value,
            TradingIntentState.RESOLVED_NO_ORDER.value,
        }:
            raise ValueError(
                f"Trade action intent '{action.id}' in state '{action.state}' cannot be completed."
            )
        action.state = TradingIntentState.PERSISTED.value
        action.response_payload = response_payload
        action.last_error = None
        self._commit()
        return self.get_action(action_intent_id) or self._to_action_domain(action)

    def mark_action_unknown(
        self,
        action_intent_id: str,
        error: str,
    ) -> TradeActionIntent:
        return self._mark_action_state(
            action_intent_id,
            TradingIntentState.UNKNOWN,
            error=error,
        )

    def mark_action_rejected(
        self,
        action_intent_id: str,
        error: str,
    ) -> TradeActionIntent:
        return self._mark_action_state(
            action_intent_id,
            TradingIntentState.REJECTED,
            error=error,
        )

    def get_action(self, action_intent_id: str) -> TradeActionIntent | None:
        record = self.session.get(TradeActionIntentRecord, action_intent_id)
        return self._to_action_domain(record) if record is not None else None

    def list_actions(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
        state: TradingIntentState | None = None,
        limit: int = 100,
    ) -> list[TradeActionIntent]:
        query = (
            select(TradeActionIntentRecord)
            .order_by(TradeActionIntentRecord.created_at.desc())
            .limit(limit)
        )
        if external_account_id is not None:
            query = query.where(TradeActionIntentRecord.external_account_id == external_account_id)
        if mode is not None:
            query = query.where(TradeActionIntentRecord.execution_mode == mode.value)
        if state is not None:
            query = query.where(TradeActionIntentRecord.state == state.value)
        return [self._to_action_domain(record) for record in self.session.execute(query).scalars().all()]

    def prepare_intent(
        self,
        *,
        external_account_id: str,
        broker: BrokerName,
        mode: ExecutionMode,
        idempotency_key: str,
        request_hash: str,
        operation: TradingOperation,
        action_context: TradingActionContext,
        broker_marker: str,
        request_payload: dict,
        target_order_id: str | None = None,
        parent_action_intent_id: str | None = None,
    ) -> PreparedBrokerOrderIntent:
        existing = self._find_by_key(
            external_account_id=external_account_id,
            mode=mode,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            self._assert_child_parent_matches(existing, parent_action_intent_id)
            return self._prepared(existing, created=False)

        broker_account_id = self._resolve_broker_account_id(external_account_id, broker)
        action: TradeActionIntentRecord | None = None
        if parent_action_intent_id is not None:
            action = self._load_action_for_update(parent_action_intent_id)
            self._assert_parent_accepts_child(
                action,
                external_account_id=external_account_id,
                broker=broker,
                mode=mode,
                child_idempotency_key=idempotency_key,
                action_context=action_context,
            )
            action_id = action.id
        else:
            action_id = str(uuid4())
            action = TradeActionIntentRecord(
                id=action_id,
                broker_account_id=broker_account_id,
                external_account_id=external_account_id,
                broker=broker.value,
                execution_mode=mode.value,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                action=action_context.action,
                strategy_id=action_context.strategy_id,
                entity_id=action_context.entity_id,
                state=TradingIntentState.PREPARED.value,
                request_payload=request_payload,
            )
        intent_id = str(uuid4())
        intent = OrderIntentRecord(
            id=intent_id,
            trade_action_intent_id=action_id,
            broker_account_id=broker_account_id,
            target_order_id=target_order_id,
            external_account_id=external_account_id,
            broker=broker.value,
            execution_mode=mode.value,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=operation.value,
            action=action_context.action,
            strategy_id=action_context.strategy_id,
            entity_id=action_context.entity_id,
            leg=action_context.leg,
            broker_marker=broker_marker,
            state=TradingIntentState.PREPARED.value,
            request_payload=request_payload,
        )
        if parent_action_intent_id is None:
            self.session.add(action)
        self.session.add(intent)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self._find_by_key(
                external_account_id=external_account_id,
                mode=mode,
                idempotency_key=idempotency_key,
            )
            if concurrent is None:
                raise
            self._assert_child_parent_matches(concurrent, parent_action_intent_id)
            return self._prepared(concurrent, created=False)
        self.session.refresh(intent)
        return self._prepared(intent, created=True)

    def mark_submitting(self, intent_id: str) -> BrokerOrderIntent:
        return self._mark_state(intent_id, TradingIntentState.SUBMITTING)

    def mark_broker_acknowledged(
        self,
        intent_id: str,
        snapshot: BrokerOrderSnapshot,
    ) -> BrokerOrderIntent:
        intent, action = self._load_pair_for_update(intent_id)
        if intent.state == TradingIntentState.PERSISTED.value:
            if intent.external_order_id == snapshot.external_order_id:
                return self._to_domain(intent)
            self._reject_late_terminal_broker_result(
                intent,
                snapshot=snapshot,
                phase="broker_acknowledged",
            )
        if intent.state in {
            TradingIntentState.REJECTED.value,
            TradingIntentState.RESOLVED_NO_ORDER.value,
        }:
            self._reject_late_terminal_broker_result(
                intent,
                snapshot=snapshot,
                phase="broker_acknowledged",
            )
        intent.state = TradingIntentState.BROKER_ACKNOWLEDGED.value
        intent.external_order_id = snapshot.external_order_id
        intent.response_payload = snapshot.model_dump(mode="json")
        intent.last_error = None
        if self._is_standalone_action_pair(intent, action):
            action.state = intent.state
            action.response_payload = intent.response_payload
            action.last_error = None
        self._commit()
        return self.get_intent(intent_id) or self._to_domain(intent)

    def persist_broker_result(
        self,
        *,
        intent_id: str,
        order: Order,
        snapshot: BrokerOrderSnapshot,
        audit_event: CreateStrategyAuditEventRequest | None,
        create_order: bool,
        reconciled: bool = False,
    ) -> Order:
        try:
            return self._persist_broker_result(
                intent_id=intent_id,
                order=order,
                snapshot=snapshot,
                audit_event=audit_event,
                create_order=create_order,
                reconciled=reconciled,
            )
        except Exception:
            self.session.rollback()
            raise

    def _persist_broker_result(
        self,
        *,
        intent_id: str,
        order: Order,
        snapshot: BrokerOrderSnapshot,
        audit_event: CreateStrategyAuditEventRequest | None,
        create_order: bool,
        reconciled: bool,
    ) -> Order:
        intent, action = self._load_pair_for_update(intent_id)
        if intent.state == TradingIntentState.PERSISTED.value:
            if (
                intent.external_order_id == snapshot.external_order_id
                and intent.response_payload is not None
            ):
                return Order.model_validate(intent.response_payload).model_copy(
                    update={"idempotent_replayed": True}
                )
            self._reject_late_terminal_broker_result(
                intent,
                snapshot=snapshot,
                phase="persist_broker_result",
            )
        if intent.state in {
            TradingIntentState.REJECTED.value,
            TradingIntentState.RESOLVED_NO_ORDER.value,
        }:
            self._reject_late_terminal_broker_result(
                intent,
                snapshot=snapshot,
                phase="persist_broker_result",
            )
        order_repository = SQLAlchemyOrderRepository(self.session, attach_intent_ledger=False)
        order_record = self.session.get(OrderRecord, order.id)
        if create_order:
            if order_record is None:
                order_record = OrderRecord(id=order.id)
                self.session.add(order_record)
        elif order_record is None:
            raise ValueError(f"Order '{order.id}' was not found while persisting broker result.")

        order = order.model_copy(
            update={
                "order_intent_id": intent.id if create_order else order.order_intent_id,
                "executed_quantity": snapshot.executed_quantity,
                "executed_price": snapshot.executed_price,
            }
        )
        with self.session.no_autoflush:
            order_repository._apply_order(order_record, order)
        self.session.flush()

        if snapshot.executed_quantity > 0:
            self._upsert_execution(order, snapshot)
        if audit_event is not None:
            audit_record = StrategyAuditEventRecord(id=audit_event.id or str(uuid4()))
            with self.session.no_autoflush:
                SQLAlchemyStrategyAuditEventRepository(self.session)._apply_request(audit_record, audit_event)
            self.session.add(audit_record)

        response_payload = order.model_dump(mode="json", exclude={"idempotent_replayed"})
        intent.state = TradingIntentState.PERSISTED.value
        intent.external_order_id = snapshot.external_order_id
        intent.response_payload = response_payload
        intent.last_error = None
        if reconciled:
            intent.last_reconciled_at = datetime.now(timezone.utc)
        if self._is_standalone_action_pair(intent, action):
            action.state = intent.state
            action.response_payload = response_payload
            action.last_error = None
        else:
            self.session.flush()
            self._settle_composite_action_after_child_terminal(
                action=action,
                trigger_intent=intent,
                actor="broker_reconciliation" if reconciled else "trading_intent_ledger",
                note=None,
                resolved_at=datetime.now(timezone.utc).isoformat(),
            )
        self._commit()
        persisted = order_repository.get_order(order.id)
        if persisted is None:
            raise RuntimeError(f"Order '{order.id}' disappeared after intent persistence.")
        return persisted

    def mark_unknown(
        self,
        intent_id: str,
        error: str,
        *,
        external_order_id: str | None = None,
    ) -> BrokerOrderIntent:
        return self._mark_state(
            intent_id,
            TradingIntentState.UNKNOWN,
            error=error,
            external_order_id=external_order_id,
        )

    def mark_rejected(self, intent_id: str, error: str) -> BrokerOrderIntent:
        return self._mark_state(intent_id, TradingIntentState.REJECTED, error=error)

    def record_reconciliation_attempt(
        self,
        intent_id: str,
        error: str,
        *,
        zero_match: bool = False,
        reconciliation_coverage_start_at: datetime | None = None,
        reconciliation_coverage_end_at: datetime | None = None,
    ) -> BrokerOrderIntent:
        intent, action = self._load_pair_for_update(intent_id)
        if intent.state in {
            TradingIntentState.PERSISTED.value,
            TradingIntentState.REJECTED.value,
            TradingIntentState.RESOLVED_NO_ORDER.value,
        }:
            return self._to_domain(intent)
        if intent.state != TradingIntentState.PERSISTED.value:
            intent.state = TradingIntentState.UNKNOWN.value
            intent.last_error = error
            if self._is_standalone_action_pair(intent, action):
                action.state = TradingIntentState.UNKNOWN.value
                action.last_error = error
        now = datetime.now(timezone.utc)
        coverage_complete = self._coverage_covers_intent(
            intent,
            reconciliation_coverage_start_at,
            reconciliation_coverage_end_at,
        )
        if not zero_match or not coverage_complete:
            # A zero-match chain is consecutive evidence.  Any positive,
            # ambiguous, or incomplete check invalidates prior no-order proof;
            # the operator must collect three new complete checks.
            intent.reconciliation_attempts = 0
            intent.first_reconciled_at = None
            intent.last_reconciled_at = None
            intent.reconciliation_coverage_start_at = None
            intent.reconciliation_coverage_end_at = None
        else:
            # Counts written before coverage evidence was persisted cannot be
            # used for a manual no-order resolution.  Start a fresh chain on
            # the first complete check after the migration (or a legacy row).
            if (
                intent.reconciliation_coverage_start_at is None
                or intent.reconciliation_coverage_end_at is None
            ):
                intent.reconciliation_attempts = 0
                intent.first_reconciled_at = None
                intent.last_reconciled_at = None
            intent.reconciliation_coverage_start_at = self._as_utc(
                reconciliation_coverage_start_at
            )
            intent.reconciliation_coverage_end_at = self._as_utc(
                reconciliation_coverage_end_at
            )
            intent.reconciliation_attempts += 1
            intent.first_reconciled_at = intent.first_reconciled_at or now
            intent.last_reconciled_at = now
        self._commit()
        return self.get_intent(intent_id) or self._to_domain(intent)

    def resolve_no_order(
        self,
        intent_id: str,
        *,
        actor: str,
        note: str | None = None,
    ) -> BrokerOrderIntent:
        intent, action = self._load_pair_for_update(intent_id)
        if intent.execution_mode != ExecutionMode.PAPER.value:
            raise PermissionError("Only paper-mode intents can be resolved as no order.")
        if (
            intent.operation == TradingOperation.SUBMIT.value
            and intent.external_order_id is not None
        ):
            raise ValueError(
                f"Trading intent '{intent.id}' already has external order id "
                f"'{intent.external_order_id}' and cannot be resolved as no order."
            )
        if intent.state not in {
            TradingIntentState.PREPARED.value,
            TradingIntentState.SUBMITTING.value,
            TradingIntentState.UNKNOWN.value,
        }:
            raise ValueError(
                f"Trading intent '{intent.id}' in state '{intent.state}' cannot be resolved as no order."
            )
        if intent.reconciliation_attempts < 3:
            raise ValueError("At least three successful zero-match reconciliations are required.")
        if intent.first_reconciled_at is None or intent.last_reconciled_at is None:
            raise ValueError("Zero-match reconciliation timestamps are incomplete.")
        if not self._coverage_covers_intent(
            intent,
            intent.reconciliation_coverage_start_at,
            intent.reconciliation_coverage_end_at,
        ):
            raise ValueError(
                "Complete broker-history coverage evidence is required for no-order resolution."
            )
        if (intent.last_reconciled_at - intent.first_reconciled_at).total_seconds() < 60:
            raise ValueError("Zero-match reconciliations must span at least 60 seconds.")
        if (
            not self._is_standalone_action_pair(intent, action)
            and action.state == TradingIntentState.PERSISTED.value
        ):
            raise ValueError(
                f"Trade action intent '{action.id}' is already persisted and cannot accept "
                "a child no-order resolution."
            )
        resolution = {
            "resolution": TradingIntentState.RESOLVED_NO_ORDER.value,
            "actor": actor,
            "note": note,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }
        intent.state = TradingIntentState.RESOLVED_NO_ORDER.value
        intent.response_payload = resolution
        intent.last_error = None
        if self._is_standalone_action_pair(intent, action):
            action.state = intent.state
            action.response_payload = resolution
            action.last_error = None
        else:
            self.session.flush()
            self._settle_composite_action_after_child_terminal(
                action=action,
                trigger_intent=intent,
                actor=actor,
                note=note,
                resolved_at=resolution["resolved_at"],
            )
        self._commit()
        return self.get_intent(intent_id) or self._to_domain(intent)

    def get_intent(self, intent_id: str) -> BrokerOrderIntent | None:
        record = self.session.get(OrderIntentRecord, intent_id)
        return self._to_domain(record) if record is not None else None

    def list_intents(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
        state: TradingIntentState | None = None,
        limit: int = 100,
    ) -> list[BrokerOrderIntent]:
        query = select(OrderIntentRecord).order_by(OrderIntentRecord.created_at.desc()).limit(limit)
        if external_account_id is not None:
            query = query.where(OrderIntentRecord.external_account_id == external_account_id)
        if mode is not None:
            query = query.where(OrderIntentRecord.execution_mode == mode.value)
        if state is not None:
            query = query.where(OrderIntentRecord.state == state.value)
        return [self._to_domain(record) for record in self.session.execute(query).scalars().all()]

    def has_unresolved_intents(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        exclude_action_intent_id: str | None = None,
    ) -> bool:
        order_intent_id = self.session.execute(
            select(OrderIntentRecord.id)
            .where(
                OrderIntentRecord.external_account_id == external_account_id,
                OrderIntentRecord.execution_mode == mode.value,
                OrderIntentRecord.state.in_(UNRESOLVED_INTENT_STATES),
            )
            .limit(1)
        ).scalar_one_or_none()
        if order_intent_id is not None:
            return True
        action_query = select(TradeActionIntentRecord.id).where(
            TradeActionIntentRecord.external_account_id == external_account_id,
            TradeActionIntentRecord.execution_mode == mode.value,
            TradeActionIntentRecord.state.in_(UNRESOLVED_INTENT_STATES),
        )
        if exclude_action_intent_id is not None:
            action_query = action_query.where(
                TradeActionIntentRecord.id != exclude_action_intent_id
            )
        action_intent_id = self.session.execute(action_query.limit(1)).scalar_one_or_none()
        return action_intent_id is not None

    def _mark_state(
        self,
        intent_id: str,
        state: TradingIntentState,
        *,
        error: str | None = None,
        external_order_id: str | None = None,
    ) -> BrokerOrderIntent:
        intent, action = self._load_pair_for_update(intent_id)
        if intent.state in {
            TradingIntentState.PERSISTED.value,
            TradingIntentState.REJECTED.value,
            TradingIntentState.RESOLVED_NO_ORDER.value,
        }:
            return self._to_domain(intent)
        intent.state = state.value
        intent.last_error = error
        if external_order_id is not None:
            intent.external_order_id = external_order_id
        if self._is_standalone_action_pair(intent, action):
            action.state = state.value
            action.last_error = error
        elif state in {
            TradingIntentState.PERSISTED,
            TradingIntentState.REJECTED,
            TradingIntentState.RESOLVED_NO_ORDER,
        }:
            self.session.flush()
            self._settle_composite_action_after_child_terminal(
                action=action,
                trigger_intent=intent,
                actor="trading_intent_ledger",
                note=None,
                resolved_at=datetime.now(timezone.utc).isoformat(),
            )
        self._commit()
        return self.get_intent(intent_id) or self._to_domain(intent)

    def _mark_action_state(
        self,
        action_intent_id: str,
        state: TradingIntentState,
        *,
        error: str,
    ) -> TradeActionIntent:
        action = self._load_action_for_update(action_intent_id)
        if action.state in {
            TradingIntentState.PERSISTED.value,
            TradingIntentState.RESOLVED_NO_ORDER.value,
        }:
            return self._to_action_domain(action)
        if action.state == TradingIntentState.REJECTED.value:
            return self._to_action_domain(action)
        action.state = state.value
        action.last_error = error
        self._commit()
        return self.get_action(action_intent_id) or self._to_action_domain(action)

    def _settle_composite_action_after_child_terminal(
        self,
        *,
        action: TradeActionIntentRecord,
        trigger_intent: OrderIntentRecord,
        actor: str,
        note: str | None,
        resolved_at: str,
    ) -> None:
        children = list(
            self.session.execute(
                select(OrderIntentRecord)
                .where(OrderIntentRecord.trade_action_intent_id == action.id)
                .with_for_update()
            ).scalars()
        )
        terminal_states = {
            TradingIntentState.PERSISTED.value,
            TradingIntentState.REJECTED.value,
            TradingIntentState.RESOLVED_NO_ORDER.value,
        }
        child_states = [
            {"intent_id": child.id, "state": child.state, "leg": child.leg}
            for child in children
        ]
        resolved_children = [
            child
            for child in children
            if child.state == TradingIntentState.RESOLVED_NO_ORDER.value
        ]
        if not resolved_children:
            return
        if not children or any(child.state not in terminal_states for child in children):
            if action.state not in {
                TradingIntentState.PERSISTED.value,
                TradingIntentState.REJECTED.value,
                TradingIntentState.RESOLVED_NO_ORDER.value,
            }:
                action.state = TradingIntentState.UNKNOWN.value
                action.last_error = (
                    f"Child intent '{resolved_children[0].id}' was resolved as no order; "
                    "other child intents still require reconciliation."
                )
            return

        resolved_child = next(
            (child for child in resolved_children if child.id == trigger_intent.id),
            resolved_children[0],
        )
        child_resolution = (
            resolved_child.response_payload
            if isinstance(resolved_child.response_payload, dict)
            else {}
        )
        resolution_actor = str(child_resolution.get("actor") or actor)
        resolution_note = child_resolution.get("note") if "note" in child_resolution else note
        resolution_time = str(child_resolution.get("resolved_at") or resolved_at)
        previous_state = action.state
        resolution = {
            "resolution": "composite_child_resolved_no_order",
            "actor": resolution_actor,
            "note": resolution_note,
            "resolved_at": resolution_time,
            "resolved_child_intent_id": resolved_child.id,
            "manual_action_required": True,
            "child_intents": child_states,
        }
        if action.state != TradingIntentState.PERSISTED.value:
            action.state = TradingIntentState.REJECTED.value
            action.response_payload = resolution
            action.last_error = (
                "Composite trade action cannot continue automatically because at least one "
                "child broker mutation was manually resolved as having no order."
            )

        event_id = str(uuid5(NAMESPACE_URL, f"trade-action-child-no-order:{action.id}"))
        if self.session.get(StrategyAuditEventRecord, event_id) is None:
            request = CreateStrategyAuditEventRequest(
                id=event_id,
                external_account_id=action.external_account_id,
                mode=ExecutionMode(action.execution_mode),
                actor=resolution_actor,
                source="trading_intent_ledger",
                strategy=action.strategy_id,
                action="composite_trade_action_resolved_no_order",
                before={"state": previous_state},
                after={"state": action.state},
                warning_code="composite_trade_action_manual_resolution_required",
                summary=(
                    "Composite trade action stopped after a child intent was manually "
                    "resolved as having no broker order."
                ),
                detail=action.last_error,
                payload={
                    **resolution,
                    "severity": "critical",
                    "trade_action_intent_id": action.id,
                },
            )
            record = StrategyAuditEventRecord(id=event_id)
            SQLAlchemyStrategyAuditEventRepository(self.session)._apply_request(record, request)
            self.session.add(record)

    def _reject_late_terminal_broker_result(
        self,
        intent: OrderIntentRecord,
        *,
        snapshot: BrokerOrderSnapshot,
        phase: str,
    ) -> None:
        event_id = str(
            uuid5(
                NAMESPACE_URL,
                "|".join(
                    (
                        "late-terminal-broker-result",
                        intent.id,
                        intent.state,
                        snapshot.external_order_id,
                    )
                ),
            )
        )
        if self.session.get(StrategyAuditEventRecord, event_id) is None:
            request = CreateStrategyAuditEventRequest(
                id=event_id,
                external_account_id=intent.external_account_id,
                mode=ExecutionMode(intent.execution_mode),
                actor="trading_intent_ledger",
                source="orders",
                strategy=intent.strategy_id,
                action="late_broker_result_after_terminal_intent",
                before={"state": intent.state},
                after={
                    "state": intent.state,
                    "external_order_id": snapshot.external_order_id,
                    "broker_order_status": snapshot.status.value,
                },
                warning_code="late_broker_result_requires_manual_action",
                summary=(
                    "Critical manual action required: a broker order appeared after its "
                    "intent had already reached a terminal state."
                ),
                detail=(
                    f"Intent {intent.id} remains {intent.state}; late broker result "
                    f"{snapshot.external_order_id} was not linked automatically."
                ),
                payload={
                    "severity": "critical",
                    "manual_action_required": True,
                    "intent_id": intent.id,
                    "trade_action_intent_id": intent.trade_action_intent_id,
                    "terminal_state": intent.state,
                    "external_order_id": snapshot.external_order_id,
                    "phase": phase,
                },
            )
            record = StrategyAuditEventRecord(id=event_id)
            SQLAlchemyStrategyAuditEventRepository(self.session)._apply_request(record, request)
            self.session.add(record)
        self._commit()
        raise ValueError(
            f"Trading intent '{intent.id}' is terminal in state '{intent.state}'; "
            f"late broker result '{snapshot.external_order_id}' requires manual action."
        )

    def _load_action_for_update(self, action_intent_id: str) -> TradeActionIntentRecord:
        action = self.session.execute(
            select(TradeActionIntentRecord)
            .where(TradeActionIntentRecord.id == action_intent_id)
            .with_for_update()
        ).scalar_one_or_none()
        if action is None:
            raise LookupError(f"Trade action intent '{action_intent_id}' was not found.")
        return action

    def _load_pair_for_update(
        self,
        intent_id: str,
    ) -> tuple[OrderIntentRecord, TradeActionIntentRecord]:
        intent = self.session.execute(
            select(OrderIntentRecord)
            .where(OrderIntentRecord.id == intent_id)
            .with_for_update()
        ).scalar_one_or_none()
        if intent is None:
            raise LookupError(f"Trading intent '{intent_id}' was not found.")
        action = self.session.execute(
            select(TradeActionIntentRecord)
            .where(TradeActionIntentRecord.id == intent.trade_action_intent_id)
            .with_for_update()
        ).scalar_one()
        return intent, action

    def _find_by_key(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        idempotency_key: str,
    ) -> OrderIntentRecord | None:
        return self.session.execute(
            select(OrderIntentRecord).where(
                OrderIntentRecord.external_account_id == external_account_id,
                OrderIntentRecord.execution_mode == mode.value,
                OrderIntentRecord.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()

    def _find_action_by_key(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        idempotency_key: str,
    ) -> TradeActionIntentRecord | None:
        return self.session.execute(
            select(TradeActionIntentRecord).where(
                TradeActionIntentRecord.external_account_id == external_account_id,
                TradeActionIntentRecord.execution_mode == mode.value,
                TradeActionIntentRecord.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()

    @staticmethod
    def _assert_child_parent_matches(
        intent: OrderIntentRecord,
        parent_action_intent_id: str | None,
    ) -> None:
        if (
            parent_action_intent_id is not None
            and intent.trade_action_intent_id != parent_action_intent_id
        ):
            raise ValueError(
                f"Order intent '{intent.id}' is already linked to a different trade action."
            )

    @staticmethod
    def _assert_action_replay_matches(
        action: TradeActionIntentRecord,
        *,
        broker: BrokerName,
        request_hash: str,
        action_context: TradingActionContext,
    ) -> None:
        if (
            action.broker != broker.value
            or action.request_hash != request_hash
            or action.action != action_context.action
            or action.strategy_id != action_context.strategy_id
            or action.entity_id != action_context.entity_id
        ):
            raise TradeActionIntentConflictError(action.id)

    @staticmethod
    def _assert_parent_accepts_child(
        action: TradeActionIntentRecord,
        *,
        external_account_id: str,
        broker: BrokerName,
        mode: ExecutionMode,
        child_idempotency_key: str,
        action_context: TradingActionContext,
    ) -> None:
        if (
            action.external_account_id != external_account_id
            or action.broker != broker.value
            or action.execution_mode != mode.value
        ):
            raise ValueError(
                f"Trade action intent '{action.id}' does not match the child order scope."
            )
        if (
            (action.strategy_id is not None and action.strategy_id != action_context.strategy_id)
            or (action.entity_id is not None and action.entity_id != action_context.entity_id)
        ):
            raise ValueError(
                f"Trade action intent '{action.id}' does not match the child strategy entity."
            )
        if action.idempotency_key == child_idempotency_key:
            raise ValueError(
                "A child order intent must use a distinct idempotency key from its parent trade action."
            )
        if action.state not in {
            TradingIntentState.PREPARED.value,
            TradingIntentState.SUBMITTING.value,
        }:
            raise ValueError(
                f"Trade action intent '{action.id}' in state '{action.state}' cannot accept a new child."
            )

    @staticmethod
    def _is_standalone_action_pair(
        intent: OrderIntentRecord,
        action: TradeActionIntentRecord,
    ) -> bool:
        # prepare_intent() without an explicit parent creates a 1:1 pair that
        # deliberately shares the idempotency key. Explicit composite parents
        # require distinct keys, so child transitions never own parent state.
        return action.idempotency_key == intent.idempotency_key

    def _prepared(self, record: OrderIntentRecord, *, created: bool) -> PreparedBrokerOrderIntent:
        replayed_order = None
        if record.state == TradingIntentState.PERSISTED.value and record.response_payload:
            replayed_order = Order.model_validate(record.response_payload).model_copy(
                update={"idempotent_replayed": True}
            )
        return PreparedBrokerOrderIntent(
            intent=self._to_domain(record),
            created=created,
            replayed_order=replayed_order,
        )

    def _upsert_execution(self, order: Order, snapshot: BrokerOrderSnapshot) -> None:
        execution_scope = ":".join(
            (
                order.broker.value,
                order.mode.value,
                order.external_account_id,
                snapshot.external_order_id or order.id,
            )
        )
        external_execution_id = (
            f"summary:v2:{hashlib.sha256(execution_scope.encode('utf-8')).hexdigest()[:40]}"
        )
        record = self.session.execute(
            select(ExecutionRecord).where(
                ExecutionRecord.external_execution_id == external_execution_id
            )
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if record is None:
            record = ExecutionRecord(id=str(uuid4()))
            self.session.add(record)
        execution = Execution(
            id=record.id,
            order_id=order.id,
            broker=order.broker,
            external_account_id=order.external_account_id,
            external_order_id=snapshot.external_order_id,
            external_execution_id=external_execution_id,
            symbol=snapshot.symbol,
            side=snapshot.side,
            quantity=snapshot.executed_quantity,
            price=snapshot.executed_price,
            executed_at=snapshot.updated_at or snapshot.submitted_at,
            raw_payload={"source": "order_detail_summary", "remote_order": snapshot.raw_payload},
            created_at=record.created_at if record.created_at is not None else now,
            updated_at=now,
        )
        SQLAlchemyExecutionRepository._apply_execution(record, execution)

    def _resolve_broker_account_id(
        self,
        external_account_id: str,
        broker: BrokerName,
    ) -> str | None:
        return self.session.execute(
            select(BrokerAccountRecord.id).where(
                BrokerAccountRecord.external_account_id == external_account_id,
                BrokerAccountRecord.broker == broker.value,
            )
        ).scalar_one_or_none()

    def _commit(self) -> None:
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _to_domain(record: OrderIntentRecord) -> BrokerOrderIntent:
        return BrokerOrderIntent(
            id=record.id,
            trade_action_intent_id=record.trade_action_intent_id,
            external_account_id=record.external_account_id,
            broker=BrokerName(record.broker),
            mode=ExecutionMode(record.execution_mode),
            idempotency_key=record.idempotency_key,
            request_hash=record.request_hash,
            operation=TradingOperation(record.operation),
            action=record.action,
            strategy_id=record.strategy_id,
            entity_id=record.entity_id,
            leg=record.leg,
            broker_marker=record.broker_marker,
            state=TradingIntentState(record.state),
            external_order_id=record.external_order_id,
            target_order_id=record.target_order_id,
            request_payload=record.request_payload,
            response_payload=record.response_payload,
            last_error=record.last_error,
            reconciliation_attempts=record.reconciliation_attempts,
            first_reconciled_at=record.first_reconciled_at,
            last_reconciled_at=record.last_reconciled_at,
            reconciliation_coverage_start_at=record.reconciliation_coverage_start_at,
            reconciliation_coverage_end_at=record.reconciliation_coverage_end_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _coverage_covers_intent(
        cls,
        intent: OrderIntentRecord,
        coverage_start_at: datetime | None,
        coverage_end_at: datetime | None,
    ) -> bool:
        if coverage_start_at is None or coverage_end_at is None:
            return False
        start_at = cls._as_utc(coverage_start_at)
        end_at = cls._as_utc(coverage_end_at)
        created_at = cls._as_utc(intent.created_at)
        return start_at <= created_at <= end_at

    @staticmethod
    def _to_action_domain(record: TradeActionIntentRecord) -> TradeActionIntent:
        return TradeActionIntent(
            id=record.id,
            external_account_id=record.external_account_id,
            broker=BrokerName(record.broker),
            mode=ExecutionMode(record.execution_mode),
            idempotency_key=record.idempotency_key,
            request_hash=record.request_hash,
            action=record.action,
            strategy_id=record.strategy_id,
            entity_id=record.entity_id,
            state=TradingIntentState(record.state),
            request_payload=record.request_payload,
            response_payload=record.response_payload,
            last_error=record.last_error,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
