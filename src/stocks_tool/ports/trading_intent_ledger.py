from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import NamedTuple, Protocol

from stocks_tool.domain.enums import BrokerName, ExecutionMode, TradingIntentState, TradingOperation
from stocks_tool.domain.models import (
    BrokerOrderIntent,
    BrokerOrderSnapshot,
    CreateStrategyAuditEventRequest,
    Order,
    PreparedBrokerOrderIntent,
    PreparedTradeActionIntent,
    TradeActionIntent,
    TradingActionContext,
)


class TradeActionIntentConflictError(RuntimeError):
    def __init__(self, intent_id: str) -> None:
        super().__init__("Trade action idempotency key was already used for a different request.")
        self.intent_id = intent_id


class ReconciliationCursor(NamedTuple):
    """Stable keyset position for one bounded unresolved-intent pass."""

    updated_at: datetime
    created_at: datetime
    intent_id: str


class TradingIntentLedger(Protocol):
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
        ...

    def mark_action_submitting(self, action_intent_id: str) -> TradeActionIntent:
        ...

    def complete_action(
        self,
        action_intent_id: str,
        response_payload: dict,
    ) -> TradeActionIntent:
        ...

    def mark_action_unknown(
        self,
        action_intent_id: str,
        error: str,
    ) -> TradeActionIntent:
        ...

    def mark_action_rejected(
        self,
        action_intent_id: str,
        error: str,
    ) -> TradeActionIntent:
        ...

    def get_action(self, action_intent_id: str) -> TradeActionIntent | None:
        ...

    def list_actions(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
        state: TradingIntentState | None = None,
        limit: int | None = 100,
    ) -> list[TradeActionIntent]:
        ...

    def count_actions(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
        state: TradingIntentState | None = None,
    ) -> int:
        ...

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
        ...

    def mark_submitting(self, intent_id: str) -> BrokerOrderIntent:
        ...

    def mark_broker_acknowledged(
        self,
        intent_id: str,
        snapshot: BrokerOrderSnapshot,
    ) -> BrokerOrderIntent:
        ...

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
        ...

    def mark_unknown(
        self,
        intent_id: str,
        error: str,
        *,
        external_order_id: str | None = None,
    ) -> BrokerOrderIntent:
        ...

    def mark_rejected(self, intent_id: str, error: str) -> BrokerOrderIntent:
        ...

    def record_reconciliation_attempt(
        self,
        intent_id: str,
        error: str,
        *,
        zero_match: bool = False,
        reconciliation_coverage_start_at: datetime | None = None,
        reconciliation_coverage_end_at: datetime | None = None,
    ) -> BrokerOrderIntent:
        ...

    def resolve_no_order(
        self,
        intent_id: str,
        *,
        actor: str,
        note: str | None = None,
    ) -> BrokerOrderIntent:
        ...

    def get_intent(self, intent_id: str) -> BrokerOrderIntent | None:
        ...

    def list_intents(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
        state: TradingIntentState | None = None,
        states: Collection[TradingIntentState] | None = None,
        operation: TradingOperation | None = None,
        operations: Collection[TradingOperation] | None = None,
        limit: int | None = 100,
    ) -> list[BrokerOrderIntent]:
        ...

    def get_reconciliation_high_watermark(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        states: Collection[TradingIntentState],
    ) -> ReconciliationCursor | None:
        """Return the latest key visible at the start of a bounded pass."""
        ...

    def list_reconciliation_intents(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        states: Collection[TradingIntentState],
        high_watermark: ReconciliationCursor,
        cursor: ReconciliationCursor | None = None,
        limit: int = 100,
    ) -> list[BrokerOrderIntent]:
        """Read one fair, keyset-bounded unresolved-intent page."""
        ...

    def count_intents(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
        state: TradingIntentState | None = None,
    ) -> int:
        ...

    def has_unresolved_intents(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        exclude_action_intent_id: str | None = None,
    ) -> bool:
        ...
