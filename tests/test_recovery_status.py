from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_recovery_status_service
from stocks_tool.application.services.recovery_status import RecoveryStatusService
from stocks_tool.domain.enums import BrokerName, ExecutionMode, TradingIntentState, TradingOperation
from stocks_tool.domain.models import (
    BrokerOrderIntent,
    MarketDataRuntimeSnapshot,
    OperatorRecoveryStatusSnapshot,
    SdkTimeoutQuarantineStatus,
    TradeActionIntent,
)
from stocks_tool.main import app
from stocks_tool.db.models import BrokerAccountRecord
from stocks_tool.domain.models import TradingActionContext
from stocks_tool.repositories.sqlalchemy_trading_intent_ledger import SQLAlchemyTradingIntentLedger
from tests.test_sqlalchemy_trading_intent_ledger import prepare, session as ledger_session


NOW = datetime(2026, 10, 2, 9, 30, tzinfo=timezone.utc)


def test_real_ledger_recovery_totals_survive_truncation_and_mode_isolation(ledger_session) -> None:
    ledger = SQLAlchemyTradingIntentLedger(ledger_session)
    for index in range(3):
        child = prepare(ledger, key=f"recovery-count-{index}").intent
        ledger.mark_unknown(child.id, "isolated fixture")
    ledger_session.add(BrokerAccountRecord(
        id="other-account", broker="longbridge", external_account_id="other-account",
    ))
    ledger_session.commit()
    for account, mode in (
        ("LBPT10087357", ExecutionMode.PAPER),
        ("LBPT10087357", ExecutionMode.LIVE),
        ("other-account", ExecutionMode.PAPER),
    ):
        parent = ledger.prepare_action(
            external_account_id=account, broker=BrokerName.LONGBRIDGE, mode=mode,
            idempotency_key="parent-only-recovery", request_hash="b" * 64,
            action_context=TradingActionContext(action="order_submit"), request_payload={},
        ).intent
        ledger.mark_action_unknown(parent.id, "isolated parent-only fixture")
    runtime = Mock()
    runtime.get_market_data_runtime_status.return_value = MarketDataRuntimeSnapshot(closed=False)
    service = RecoveryStatusService(intent_ledger=ledger, runtime_gateway=runtime)

    snapshot = service.get_status(external_account_id="LBPT10087357", mode=ExecutionMode.PAPER, limit=1)
    assert snapshot.recovery_blocked and snapshot.truncated
    assert snapshot.unresolved_count == snapshot.unknown_count == 3
    assert snapshot.displayed_unresolved_count == 1
    assert snapshot.unresolved_parent_count == snapshot.unknown_parent_count == 4
    assert all(item.mode == ExecutionMode.PAPER and item.external_account_id == "LBPT10087357" for item in snapshot.intents)

    for account, mode in (("LBPT10087357", ExecutionMode.LIVE), ("other-account", ExecutionMode.PAPER)):
        parent_only = service.get_status(external_account_id=account, mode=mode, limit=1)
        assert parent_only.recovery_blocked
        assert parent_only.unresolved_count == 0
        assert parent_only.unresolved_parent_count == 1
        assert parent_only.primary_blocker == "order_outcome_unknown"


def _intent(
    *,
    intent_id: str = "child-1",
    action_id: str = "parent-1",
    state: TradingIntentState = TradingIntentState.UNKNOWN,
    attempts: int = 1,
    coverage_start: datetime | None = None,
    coverage_end: datetime | None = None,
    first: datetime | None = None,
    last: datetime | None = None,
) -> BrokerOrderIntent:
    return BrokerOrderIntent(
        id=intent_id,
        trade_action_intent_id=action_id,
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        idempotency_key=f"key-{intent_id}",
        request_hash="a" * 64,
        operation=TradingOperation.SUBMIT,
        action="bull_put_entry_long",
        strategy_id="paper_bull_put_v1",
        entity_id="spread-1",
        leg="long_entry",
        broker_marker=f"marker-{intent_id}",
        state=state,
        request_payload={"symbol": "QQQ.US"},
        last_error="broker response timed out",
        reconciliation_attempts=attempts,
        first_reconciled_at=first,
        last_reconciled_at=last,
        reconciliation_coverage_start_at=coverage_start,
        reconciliation_coverage_end_at=coverage_end,
        created_at=NOW,
        updated_at=NOW,
    )


def _parent(
    *,
    state: TradingIntentState = TradingIntentState.UNKNOWN,
    idempotency_key: str = "parent-key",
) -> TradeActionIntent:
    return TradeActionIntent(
        id="parent-1",
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        idempotency_key=idempotency_key,
        request_hash="b" * 64,
        action="bull_put_execute",
        strategy_id="paper_bull_put_v1",
        entity_id="spread-1",
        state=state,
        request_payload={"symbol": "QQQ.US"},
        created_at=NOW,
        updated_at=NOW,
    )


def _service(intent: BrokerOrderIntent) -> tuple[RecoveryStatusService, Mock, Mock]:
    ledger = Mock()
    ledger.list_intents.side_effect = lambda **kwargs: (
        [intent] if kwargs["state"] == intent.state else []
    )
    ledger.count_intents.side_effect = lambda **kwargs: (
        1 if kwargs["state"] == intent.state else 0
    )
    ledger.get_action.return_value = _parent()
    ledger.list_actions.side_effect = lambda **kwargs: (
        [_parent()] if kwargs["state"] == _parent().state else []
    )
    ledger.count_actions.side_effect = lambda **kwargs: (
        1 if kwargs["state"] == _parent().state else 0
    )
    ledger.has_unresolved_intents.return_value = True
    runtime = Mock()
    runtime.get_market_data_runtime_status.return_value = MarketDataRuntimeSnapshot(
        closed=False,
        sdk_quarantine=SdkTimeoutQuarantineStatus(
            pending_count=1,
            oldest_started_at=NOW - timedelta(seconds=14),
            oldest_duration_seconds=14,
            next_action="Wait for the timed-out SDK call to finish.",
        ),
    )
    return RecoveryStatusService(intent_ledger=ledger, runtime_gateway=runtime), ledger, runtime


def test_recovery_status_exposes_parent_child_coverage_and_sdk_quarantine() -> None:
    service, ledger, runtime = _service(_intent(attempts=1))

    snapshot = service.get_status(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    )

    assert snapshot.status == "blocked"
    assert snapshot.primary_blocker == "reconciliation_checks_pending"
    assert snapshot.recovery_blocked is True
    assert snapshot.intents[0].trade_action_intent_id == "parent-1"
    assert snapshot.intents[0].coverage_covers_intent is False
    assert snapshot.parents[0].action == "bull_put_execute"
    assert snapshot.sdk_quarantine.pending_count == 1
    runtime.get_market_data_runtime_status.assert_called_once_with()


def test_recovery_status_marks_complete_no_order_evidence_without_resolving() -> None:
    intent = _intent(
        attempts=3,
        coverage_start=NOW - timedelta(minutes=5),
        coverage_end=NOW + timedelta(minutes=1),
        first=NOW,
        last=NOW + timedelta(seconds=60),
    )
    service, _, runtime = _service(intent)
    runtime.get_market_data_runtime_status.return_value = MarketDataRuntimeSnapshot(
        closed=False,
        sdk_quarantine=SdkTimeoutQuarantineStatus(),
    )

    snapshot = service.get_status(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    )

    assert snapshot.status == "blocked"
    assert snapshot.recovery_blocked is True
    assert snapshot.intents[0].coverage_covers_intent is True
    assert snapshot.intents[0].checks_satisfied is True
    assert snapshot.intents[0].reason_code == "reconciliation_evidence_ready"
    assert snapshot.sdk_quarantine.pending_count == 0


def test_recovery_status_route_is_read_only_and_returns_snapshot() -> None:
    service = Mock()
    service.get_status.return_value = OperatorRecoveryStatusSnapshot(
        generated_at=NOW,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        status="clear",
        recovery_blocked=False,
        next_action="No unresolved order intent or SDK timeout quarantine is currently recorded.",
    )
    app.dependency_overrides[get_recovery_status_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.get(
            "/ops/recovery-status",
            params={"external_account_id": "LBPT10087357", "mode": "paper", "limit": 25},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["recovery_blocked"] is False
    service.get_status.assert_called_once_with(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        limit=25,
    )


def test_recovery_status_does_not_drop_parent_only_unknown_action() -> None:
    ledger = Mock()
    ledger.list_intents.return_value = []
    ledger.count_intents.return_value = 0
    ledger.list_actions.side_effect = lambda **kwargs: (
        [_parent()] if kwargs["state"] == TradingIntentState.UNKNOWN else []
    )
    ledger.count_actions.side_effect = lambda **kwargs: (
        1 if kwargs["state"] == TradingIntentState.UNKNOWN else 0
    )
    ledger.has_unresolved_intents.return_value = True
    runtime = Mock()
    runtime.get_market_data_runtime_status.return_value = MarketDataRuntimeSnapshot(
        closed=False,
        sdk_quarantine=SdkTimeoutQuarantineStatus(),
    )
    service = RecoveryStatusService(intent_ledger=ledger, runtime_gateway=runtime)

    snapshot = service.get_status(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    )

    assert snapshot.recovery_blocked is True
    assert snapshot.status == "blocked"
    assert snapshot.unresolved_count == 0
    assert snapshot.unresolved_parent_count == 1
    assert snapshot.displayed_parent_count == 1
    assert snapshot.primary_blocker == "order_outcome_unknown"
    assert snapshot.parents[0].child_count == 0


def test_recovery_status_reuses_parent_persisted_resolution_policy() -> None:
    intent = _intent(
        attempts=3,
        coverage_start=NOW - timedelta(minutes=5),
        coverage_end=NOW + timedelta(minutes=1),
        first=NOW,
        last=NOW + timedelta(seconds=60),
    )
    ledger = Mock()
    ledger.list_intents.side_effect = lambda **kwargs: (
        [intent] if kwargs["state"] == intent.state else []
    )
    ledger.count_intents.side_effect = lambda **kwargs: (
        1 if kwargs["state"] == intent.state else 0
    )
    persisted_parent = _parent(state=TradingIntentState.PERSISTED)
    ledger.get_action.return_value = persisted_parent
    ledger.list_actions.return_value = []
    ledger.count_actions.return_value = 0
    ledger.has_unresolved_intents.return_value = True
    runtime = Mock()
    runtime.get_market_data_runtime_status.return_value = MarketDataRuntimeSnapshot(
        closed=False,
        sdk_quarantine=SdkTimeoutQuarantineStatus(),
    )
    service = RecoveryStatusService(intent_ledger=ledger, runtime_gateway=runtime)

    snapshot = service.get_status(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    )

    child = snapshot.intents[0]
    assert child.checks_satisfied is False
    assert child.reason_code == "parent_action_persisted"
