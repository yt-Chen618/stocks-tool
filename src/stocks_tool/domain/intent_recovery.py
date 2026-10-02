from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from stocks_tool.domain.enums import ExecutionMode, TradingIntentState, TradingOperation
from stocks_tool.domain.models import BrokerOrderIntent, TradeActionIntent


UNRESOLVED_INTENT_STATES = frozenset(
    {
        TradingIntentState.PREPARED,
        TradingIntentState.SUBMITTING,
        TradingIntentState.BROKER_ACKNOWLEDGED,
        TradingIntentState.UNKNOWN,
    }
)

NO_ORDER_RESOLUTION_STATES = frozenset(
    {
        TradingIntentState.PREPARED,
        TradingIntentState.SUBMITTING,
        TradingIntentState.UNKNOWN,
    }
)


@dataclass(frozen=True)
class NoOrderResolutionPolicy:
    eligible: bool
    reason_code: str
    detail: str
    next_action: str
    message: str
    permission_denied: bool = False
    coverage_covers_intent: bool = False
    check_span_seconds: int | None = None


def covers_intent_creation(
    *,
    created_at: datetime,
    coverage_start_at: datetime | None,
    coverage_end_at: datetime | None,
) -> bool:
    if coverage_start_at is None or coverage_end_at is None:
        return False
    created = _as_utc(created_at)
    return _as_utc(coverage_start_at) <= created <= _as_utc(coverage_end_at)


def reconciliation_span_seconds(
    *,
    first_reconciled_at: datetime | None,
    last_reconciled_at: datetime | None,
) -> int | None:
    if first_reconciled_at is None or last_reconciled_at is None:
        return None
    return max(
        0,
        int(
            (
                _as_utc(last_reconciled_at)
                - _as_utc(first_reconciled_at)
            ).total_seconds()
        ),
    )


def evaluate_no_order_resolution(
    intent: BrokerOrderIntent,
    parent_action: TradeActionIntent | None,
) -> NoOrderResolutionPolicy:
    """Return the single source of truth for paper no-order resolution evidence.

    The result is descriptive and side-effect free.  The ledger uses its
    ``message`` when enforcing a resolution, while operator read-models use the
    evidence and guidance fields without granting any action permission.
    """

    coverage_covers_intent = covers_intent_creation(
        created_at=intent.created_at,
        coverage_start_at=intent.reconciliation_coverage_start_at,
        coverage_end_at=intent.reconciliation_coverage_end_at,
    )
    span_seconds = reconciliation_span_seconds(
        first_reconciled_at=intent.first_reconciled_at,
        last_reconciled_at=intent.last_reconciled_at,
    )

    if intent.mode != ExecutionMode.PAPER:
        return NoOrderResolutionPolicy(
            eligible=False,
            reason_code="paper_resolution_not_allowed",
            detail="Only paper-mode intents can be reviewed for no-order resolution.",
            next_action="Keep the intent blocked and review the live broker outcome manually.",
            message="Only paper-mode intents can be resolved as no order.",
            permission_denied=True,
            coverage_covers_intent=coverage_covers_intent,
            check_span_seconds=span_seconds,
        )
    if intent.operation == TradingOperation.SUBMIT and intent.external_order_id is not None:
        return NoOrderResolutionPolicy(
            eligible=False,
            reason_code="external_order_id_present",
            detail="An external order id is already recorded for this submit intent.",
            next_action="Inspect and reconcile the recorded broker order instead of treating it as no order.",
            message=(
                f"Trading intent '{intent.id}' already has external order id "
                f"'{intent.external_order_id}' and cannot be resolved as no order."
            ),
            coverage_covers_intent=coverage_covers_intent,
            check_span_seconds=span_seconds,
        )
    if intent.state not in NO_ORDER_RESOLUTION_STATES:
        return NoOrderResolutionPolicy(
            eligible=False,
            reason_code="intent_state_not_resolvable",
            detail=f"The intent is in '{intent.state.value}' and is not in a no-order review state.",
            next_action="Keep the intent blocked and review its existing lifecycle state.",
            message=(
                f"Trading intent '{intent.id}' in state '{intent.state.value}' "
                "cannot be resolved as no order."
            ),
            coverage_covers_intent=coverage_covers_intent,
            check_span_seconds=span_seconds,
        )
    if intent.reconciliation_attempts < 3:
        return NoOrderResolutionPolicy(
            eligible=False,
            reason_code="reconciliation_checks_pending",
            detail=(
                f"{intent.reconciliation_attempts} of 3 complete zero-match checks are recorded."
            ),
            next_action="Let the existing reconciliation process collect the remaining complete checks; do not retry a broker mutation.",
            message="At least three successful zero-match reconciliations are required.",
            coverage_covers_intent=coverage_covers_intent,
            check_span_seconds=span_seconds,
        )
    if intent.first_reconciled_at is None or intent.last_reconciled_at is None:
        return NoOrderResolutionPolicy(
            eligible=False,
            reason_code="reconciliation_timestamps_incomplete",
            detail="The first and latest reconciliation timestamps are incomplete.",
            next_action="Wait for complete reconciliation timestamps; do not retry a broker mutation.",
            message="Zero-match reconciliation timestamps are incomplete.",
            coverage_covers_intent=coverage_covers_intent,
            check_span_seconds=span_seconds,
        )
    if not coverage_covers_intent:
        return NoOrderResolutionPolicy(
            eligible=False,
            reason_code="reconciliation_coverage_incomplete",
            detail="The broker-history evidence does not cover the intent creation time.",
            next_action="Wait for the existing reconciliation process to record a complete history window; do not retry a broker mutation.",
            message="Complete broker-history coverage evidence is required for no-order resolution.",
            coverage_covers_intent=False,
            check_span_seconds=span_seconds,
        )
    if span_seconds is None or span_seconds < 60:
        return NoOrderResolutionPolicy(
            eligible=False,
            reason_code="reconciliation_wait_window",
            detail="The zero-match checks have not yet spanned the required 60 seconds.",
            next_action="Wait until the existing evidence chain spans 60 seconds before any local review; do not retry a broker mutation.",
            message="Zero-match reconciliations must span at least 60 seconds.",
            coverage_covers_intent=True,
            check_span_seconds=span_seconds,
        )
    if parent_action is None:
        return NoOrderResolutionPolicy(
            eligible=False,
            reason_code="parent_intent_missing",
            detail="The parent trade action cannot be read for this child intent.",
            next_action="Keep the child blocked until its parent trade action is readable.",
            message="The parent trade action intent could not be loaded.",
            coverage_covers_intent=True,
            check_span_seconds=span_seconds,
        )
    if (
        parent_action.idempotency_key != intent.idempotency_key
        and parent_action.state == TradingIntentState.PERSISTED
    ):
        return NoOrderResolutionPolicy(
            eligible=False,
            reason_code="parent_action_persisted",
            detail="The parent trade action is already persisted and cannot accept a child no-order resolution.",
            next_action="Review the persisted parent action and reconcile this child within that existing action.",
            message=(
                f"Trade action intent '{parent_action.id}' is already persisted and cannot accept "
                "a child no-order resolution."
            ),
            coverage_covers_intent=True,
            check_span_seconds=span_seconds,
        )
    return NoOrderResolutionPolicy(
        eligible=True,
        reason_code="reconciliation_evidence_ready",
        detail="The read-only no-order evidence chain meets its count, coverage, time, and parent-state checks.",
        next_action="Review the evidence before any local paper resolution; this view never retries or resolves the intent.",
        message="",
        coverage_covers_intent=True,
        check_span_seconds=span_seconds,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
