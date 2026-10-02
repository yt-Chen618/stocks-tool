from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from stocks_tool.domain.enums import ExecutionMode, TradingIntentState
from stocks_tool.domain.intent_recovery import (
    UNRESOLVED_INTENT_STATES,
    evaluate_no_order_resolution,
)
from stocks_tool.domain.models import (
    BrokerOrderIntent,
    MarketDataRuntimeSnapshot,
    OperatorRecoveryIntent,
    OperatorRecoveryParent,
    OperatorRecoveryStatusSnapshot,
    SdkTimeoutQuarantineStatus,
    TradeActionIntent,
)
from stocks_tool.ports.trading_intent_ledger import TradingIntentLedger


class RecoveryRuntimeGateway(Protocol):
    def get_market_data_runtime_status(self) -> MarketDataRuntimeSnapshot:
        """Return local SDK state without opening a broker connection."""


class RecoveryStatusService:
    """Compose existing intent and broker runtime evidence for operator display.

    The service is read-only.  Reconciliation remains owned by the scheduler and
    the existing intent ledger, and no broker order or history operation is called.
    """

    def __init__(
        self,
        *,
        intent_ledger: TradingIntentLedger,
        runtime_gateway: RecoveryRuntimeGateway,
    ) -> None:
        self.intent_ledger = intent_ledger
        self.runtime_gateway = runtime_gateway

    def get_status(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        limit: int = 100,
    ) -> OperatorRecoveryStatusSnapshot:
        generated_at = datetime.now(timezone.utc)
        intent_counts = self._count_by_state(
            kind="intent",
            external_account_id=external_account_id,
            mode=mode,
        )
        action_counts = self._count_by_state(
            kind="action",
            external_account_id=external_account_id,
            mode=mode,
        )
        intents = self._list_unresolved_intents(
            external_account_id=external_account_id,
            mode=mode,
            limit=limit,
        )
        listed_actions = self._list_unresolved_actions(
            external_account_id=external_account_id,
            mode=mode,
            limit=limit,
        )

        parent_actions: dict[str, TradeActionIntent | None] = {
            action.id: action for action in listed_actions
        }
        recovery_intents: list[OperatorRecoveryIntent] = []
        for intent in intents:
            if intent.trade_action_intent_id not in parent_actions:
                # A persisted parent may still own an unresolved child and is
                # intentionally read for context even though it is not itself
                # in the unresolved-parent count.
                parent_actions[intent.trade_action_intent_id] = self.intent_ledger.get_action(
                    intent.trade_action_intent_id
                )
            recovery_intents.append(
                self._to_recovery_intent(
                    intent,
                    parent_action=parent_actions[intent.trade_action_intent_id],
                )
            )

        parents = self._build_parent_summaries(
            recovery_intents,
            parent_actions,
            external_account_id=external_account_id,
            mode=mode,
            children_truncated=(
                intent_counts["total"] > len(recovery_intents)
            ),
        )
        sdk_quarantine = self._sdk_quarantine_status()
        authoritative_blocked = self.intent_ledger.has_unresolved_intents(
            external_account_id=external_account_id,
            mode=mode,
        )
        primary_blocker, next_action = self._overall_guidance(
            recovery_intents,
            parents,
            sdk_quarantine,
            authoritative_blocked=authoritative_blocked,
        )

        displayed_unknown_count = sum(
            intent.state == TradingIntentState.UNKNOWN for intent in recovery_intents
        )
        displayed_unknown_parent_count = sum(
            parent.state == TradingIntentState.UNKNOWN for parent in parents
        )
        unresolved_count = intent_counts["total"]
        unresolved_parent_count = action_counts["total"]
        displayed_parent_count = len(parents)
        truncated = (
            len(recovery_intents) < unresolved_count
            or len(listed_actions) < unresolved_parent_count
        )
        recovery_blocked = (
            authoritative_blocked
            or sdk_quarantine.pending_count > 0
            or not sdk_quarantine.available
        )
        return OperatorRecoveryStatusSnapshot(
            generated_at=generated_at,
            external_account_id=external_account_id,
            mode=mode,
            status="blocked" if recovery_blocked else "clear",
            recovery_blocked=recovery_blocked,
            unresolved_count=unresolved_count,
            displayed_unresolved_count=len(recovery_intents),
            unknown_count=intent_counts["unknown"],
            displayed_unknown_count=displayed_unknown_count,
            unresolved_parent_count=unresolved_parent_count,
            displayed_parent_count=displayed_parent_count,
            unknown_parent_count=action_counts["unknown"],
            displayed_unknown_parent_count=displayed_unknown_parent_count,
            truncated=truncated,
            primary_blocker=primary_blocker,
            next_action=next_action,
            parents=parents,
            intents=recovery_intents,
            sdk_quarantine=sdk_quarantine,
        )

    def _count_by_state(
        self,
        *,
        kind: str,
        external_account_id: str,
        mode: ExecutionMode,
    ) -> dict[str, int]:
        counter = (
            self.intent_ledger.count_intents
            if kind == "intent"
            else self.intent_ledger.count_actions
        )
        counts = {
            state.value: counter(
                external_account_id=external_account_id,
                mode=mode,
                state=state,
            )
            for state in UNRESOLVED_INTENT_STATES
        }
        return {
            "total": sum(counts.values()),
            "unknown": counts.get(TradingIntentState.UNKNOWN.value, 0),
        }

    def _list_unresolved_intents(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        limit: int,
    ) -> list[BrokerOrderIntent]:
        by_id: dict[str, BrokerOrderIntent] = {}
        for state in UNRESOLVED_INTENT_STATES:
            for intent in self.intent_ledger.list_intents(
                external_account_id=external_account_id,
                mode=mode,
                state=state,
                limit=limit,
            ):
                by_id[intent.id] = intent
        return sorted(
            by_id.values(),
            key=lambda intent: self._as_utc(intent.created_at),
            reverse=True,
        )[:limit]

    def _list_unresolved_actions(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        limit: int,
    ) -> list[TradeActionIntent]:
        by_id: dict[str, TradeActionIntent] = {}
        for state in UNRESOLVED_INTENT_STATES:
            for action in self.intent_ledger.list_actions(
                external_account_id=external_account_id,
                mode=mode,
                state=state,
                limit=limit,
            ):
                by_id[action.id] = action
        return sorted(
            by_id.values(),
            key=lambda action: self._as_utc(action.created_at),
            reverse=True,
        )[:limit]

    def _sdk_quarantine_status(self) -> SdkTimeoutQuarantineStatus:
        try:
            runtime = self.runtime_gateway.get_market_data_runtime_status()
        except Exception:
            # A local observability failure must not be treated as proof that
            # the quarantine is empty.  Keep the recovery posture conservative.
            return SdkTimeoutQuarantineStatus(
                available=False,
                next_action=(
                    "SDK timeout quarantine status is unavailable. Keep recovery blocked "
                    "until local runtime state can be read."
                ),
            )
        return runtime.sdk_quarantine

    @classmethod
    def _to_recovery_intent(
        cls,
        intent: BrokerOrderIntent,
        *,
        parent_action: TradeActionIntent | None,
    ) -> OperatorRecoveryIntent:
        policy = evaluate_no_order_resolution(intent, parent_action)
        return OperatorRecoveryIntent(
            id=intent.id,
            trade_action_intent_id=intent.trade_action_intent_id,
            external_account_id=intent.external_account_id,
            mode=intent.mode,
            operation=intent.operation,
            action=intent.action,
            strategy_id=intent.strategy_id,
            entity_id=intent.entity_id,
            leg=intent.leg,
            state=intent.state,
            external_order_id=intent.external_order_id,
            target_order_id=intent.target_order_id,
            parent_action=parent_action.action if parent_action else None,
            parent_state=parent_action.state if parent_action else None,
            created_at=intent.created_at,
            updated_at=intent.updated_at,
            reconciliation_attempts=intent.reconciliation_attempts,
            first_reconciled_at=intent.first_reconciled_at,
            last_reconciled_at=intent.last_reconciled_at,
            coverage_start_at=intent.reconciliation_coverage_start_at,
            coverage_end_at=intent.reconciliation_coverage_end_at,
            coverage_covers_intent=policy.coverage_covers_intent,
            checks_satisfied=policy.eligible,
            check_span_seconds=policy.check_span_seconds,
            reason_code=policy.reason_code,
            reason_detail=policy.detail,
            next_action=policy.next_action,
        )

    @classmethod
    def _build_parent_summaries(
        cls,
        intents: list[OperatorRecoveryIntent],
        parent_actions: dict[str, TradeActionIntent | None],
        *,
        external_account_id: str,
        mode: ExecutionMode,
        children_truncated: bool,
    ) -> list[OperatorRecoveryParent]:
        grouped: dict[str, list[OperatorRecoveryIntent]] = {}
        for intent in intents:
            grouped.setdefault(intent.trade_action_intent_id, []).append(intent)
        parents: list[OperatorRecoveryParent] = []
        for action_id, parent in parent_actions.items():
            children = grouped.get(action_id, [])
            if children:
                selected = cls._select_guidance(children)
                reason_code, next_action = selected.reason_code, selected.next_action
                evidence_ready_count = sum(child.checks_satisfied for child in children)
            elif parent is not None:
                reason_code, next_action = cls._parent_guidance(parent)
                evidence_ready_count = 0
            else:
                reason_code = "parent_intent_missing"
                next_action = "Keep recovery blocked until the parent trade action is readable."
                evidence_ready_count = 0
            parents.append(
                OperatorRecoveryParent(
                    id=action_id,
                    external_account_id=external_account_id,
                    mode=mode,
                    action=parent.action if parent else None,
                    strategy_id=parent.strategy_id if parent else None,
                    entity_id=parent.entity_id if parent else None,
                    state=parent.state if parent else None,
                    child_count=len(children),
                    unresolved_child_count=len(children),
                    evidence_ready_child_count=evidence_ready_count,
                    children_truncated=children_truncated and bool(children),
                    reason_code=reason_code,
                    next_action=next_action,
                )
            )
        return sorted(parents, key=lambda parent: parent.id)

    @staticmethod
    def _parent_guidance(parent: TradeActionIntent) -> tuple[str, str]:
        if parent.state == TradingIntentState.UNKNOWN:
            return (
                "order_outcome_unknown",
                "Review the parent trade action and wait for its child reconciliation evidence; do not retry a broker mutation.",
            )
        return (
            "order_reconciliation_pending",
            "Review the parent trade action and allow the existing reconciliation process to continue; do not retry a broker mutation.",
        )

    @staticmethod
    def _select_guidance(
        intents: list[OperatorRecoveryIntent],
    ) -> OperatorRecoveryIntent:
        priority = {
            "parent_action_persisted": 0,
            "external_order_id_present": 1,
            "reconciliation_coverage_incomplete": 2,
            "reconciliation_checks_pending": 3,
            "reconciliation_timestamps_incomplete": 4,
            "reconciliation_wait_window": 5,
            "intent_state_not_resolvable": 6,
            "order_outcome_unknown": 7,
            "order_reconciliation_pending": 8,
            "reconciliation_evidence_ready": 9,
        }
        return min(intents, key=lambda item: priority.get(item.reason_code, 99))

    @classmethod
    def _overall_guidance(
        cls,
        intents: list[OperatorRecoveryIntent],
        parents: list[OperatorRecoveryParent],
        sdk_quarantine: SdkTimeoutQuarantineStatus,
        *,
        authoritative_blocked: bool,
    ) -> tuple[str | None, str]:
        actions: list[str] = []
        primary_blocker: str | None = None
        if intents:
            selected = cls._select_guidance(intents)
            primary_blocker = selected.reason_code
            actions.append(selected.next_action)
        elif parents:
            selected_parent = min(
                parents,
                key=lambda parent: {
                    "order_outcome_unknown": 0,
                    "order_reconciliation_pending": 1,
                    "parent_intent_missing": 2,
                }.get(parent.reason_code or "", 99),
            )
            primary_blocker = selected_parent.reason_code
            if selected_parent.next_action:
                actions.append(selected_parent.next_action)
        elif authoritative_blocked:
            primary_blocker = "order_reconciliation_pending"
            actions.append(
                "Unresolved order recovery evidence exists but is outside this page; review the full ledger before any broker mutation."
            )
        if not sdk_quarantine.available:
            primary_blocker = primary_blocker or "sdk_runtime_unavailable"
            if sdk_quarantine.next_action:
                actions.append(sdk_quarantine.next_action)
        elif sdk_quarantine.pending_count > 0:
            primary_blocker = primary_blocker or "sdk_timeout_quarantine"
            if sdk_quarantine.next_action:
                actions.append(sdk_quarantine.next_action)
        if not actions:
            return None, "No unresolved order intent or SDK timeout quarantine is currently recorded."
        return primary_blocker, " ".join(dict.fromkeys(actions))

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
