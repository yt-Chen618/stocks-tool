from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.db.base import Base
from stocks_tool.db.models import (
    BrokerAccountRecord,
    ExecutionRecord,
    OrderIntentRecord,
    OrderRecord,
    StrategyAuditEventRecord,
    TradeActionIntentRecord,
)
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    TradingIntentState,
    TradingOperation,
    SpreadStatus,
)
from stocks_tool.domain.intent_recovery import evaluate_no_order_resolution
from stocks_tool.domain.models import (
    BrokerOrderSnapshot,
    CreateStrategyAuditEventRequest,
    Order,
    TradingActionContext,
    BullPutSpread,
)
from stocks_tool.ports.repository import ConcurrentSpreadUpdateError
from stocks_tool.ports.trading_intent_ledger import TradeActionIntentConflictError
from stocks_tool.repositories.sqlalchemy_bull_put_spread_repository import (
    SQLAlchemyBullPutSpreadRepository,
)
from stocks_tool.repositories.sqlalchemy_trading_intent_ledger import (
    SQLAlchemyTradingIntentLedger,
)
from stocks_tool.repositories.sqlalchemy_order_repository import SQLAlchemyOrderRepository


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


NOW = datetime(2026, 7, 11, 14, 30, tzinfo=timezone.utc)
COVERAGE_START = datetime(2000, 1, 1, tzinfo=timezone.utc)
COVERAGE_END = datetime(2100, 1, 1, tzinfo=timezone.utc)


def coverage_kwargs() -> dict[str, datetime]:
    return {
        "reconciliation_coverage_start_at": COVERAGE_START,
        "reconciliation_coverage_end_at": COVERAGE_END,
    }


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as db_session:
        db_session.add(
            BrokerAccountRecord(
                id="broker-account-1",
                broker=BrokerName.LONGBRIDGE.value,
                external_account_id="LBPT10087357",
                is_active=True,
            )
        )
        db_session.commit()
        yield db_session
    engine.dispose()


def remote_snapshot() -> BrokerOrderSnapshot:
    return BrokerOrderSnapshot(
        external_order_id="external-order-1",
        symbol="UNH.US",
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.FILLED,
        limit_price=Decimal("321.00"),
        executed_quantity=1,
        executed_price=Decimal("320.75"),
        remark="st:0123456789abcdef",
        submitted_at=NOW,
        updated_at=NOW,
        raw_payload={"order_id": "external-order-1", "remark": "st:0123456789abcdef"},
    )


def local_order(intent_id: str) -> Order:
    return Order(
        id="order-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id="external-order-1",
        client_order_id="local-order-1",
        order_intent_id=intent_id,
        symbol="UNH.US",
        asset_type=AssetType.STOCK,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.FILLED,
        executed_quantity=1,
        executed_price=Decimal("320.75"),
        limit_price=Decimal("321.00"),
        submitted_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def prepare(ledger: SQLAlchemyTradingIntentLedger, key: str = "strategy-order-key-0001"):
    return ledger.prepare_intent(
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        idempotency_key=key,
        request_hash="a" * 64,
        operation=TradingOperation.SUBMIT,
        action_context=TradingActionContext(action="order_submit"),
        broker_marker="st:0123456789abcdef",
        request_payload={
            "external_account_id": "LBPT10087357",
            "symbol": "UNH.US",
            "side": "buy",
            "quantity": 1,
            "order_type": "limit",
            "time_in_force": "day",
            "mode": "paper",
            "limit_price": "321.00",
        },
    )


def test_ledger_atomically_persists_order_execution_audit_and_replays(session: Session) -> None:
    ledger = SQLAlchemyTradingIntentLedger(session)
    prepared = prepare(ledger)
    ledger.mark_submitting(prepared.intent.id)
    ledger.mark_broker_acknowledged(prepared.intent.id, remote_snapshot())
    order = local_order(prepared.intent.id)

    persisted = ledger.persist_broker_result(
        intent_id=prepared.intent.id,
        order=order,
        snapshot=remote_snapshot(),
        audit_event=CreateStrategyAuditEventRequest(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            action="paper_order_submitted",
            order_ids=[order.id],
        ),
        create_order=True,
    )

    assert persisted.executed_quantity == 1
    assert persisted.executed_price == Decimal("320.7500")
    assert ledger.get_intent(prepared.intent.id).state == TradingIntentState.PERSISTED
    standalone_action = ledger.get_action(prepared.intent.trade_action_intent_id)
    assert standalone_action is not None
    assert standalone_action.state == TradingIntentState.PERSISTED
    assert standalone_action.response_payload is not None
    assert standalone_action.response_payload["id"] == "order-1"
    assert session.scalar(select(func.count()).select_from(OrderRecord)) == 1
    assert session.scalar(select(func.count()).select_from(ExecutionRecord)) == 1
    assert session.scalar(select(func.count()).select_from(StrategyAuditEventRecord)) == 1

    replay = prepare(ledger)
    assert replay.created is False
    assert replay.replayed_order is not None
    assert replay.replayed_order.id == "order-1"
    assert replay.replayed_order.idempotent_replayed is True


def test_trade_action_prepare_replays_same_hash_and_conflicts_on_changed_hash(
    session: Session,
) -> None:
    ledger = SQLAlchemyTradingIntentLedger(session)
    kwargs = {
        "external_account_id": "LBPT10087357",
        "broker": BrokerName.LONGBRIDGE,
        "mode": ExecutionMode.PAPER,
        "idempotency_key": "bull-put-public-action-0001",
        "request_hash": "b" * 64,
        "action_context": TradingActionContext(
            action="bull_put_execute",
            strategy_id="paper_bull_put_v1",
            entity_id="spread-1",
        ),
        "request_payload": {"symbol": "QQQ.US", "confirm_paper_order": True},
    }

    created = ledger.prepare_action(**kwargs)
    replayed = ledger.prepare_action(**kwargs)

    assert created.created is True
    assert replayed.created is False
    assert replayed.intent.id == created.intent.id
    assert session.scalar(select(func.count()).select_from(TradeActionIntentRecord)) == 1

    with pytest.raises(TradeActionIntentConflictError) as exc_info:
        ledger.prepare_action(**{**kwargs, "request_hash": "c" * 64})

    assert exc_info.value.intent_id == created.intent.id
    assert session.scalar(select(func.count()).select_from(TradeActionIntentRecord)) == 1


def test_two_child_order_intents_share_parent_without_overwriting_parent_state(
    session: Session,
) -> None:
    ledger = SQLAlchemyTradingIntentLedger(session)
    parent = ledger.prepare_action(
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        idempotency_key="bull-put-public-action-0002",
        request_hash="d" * 64,
        action_context=TradingActionContext(
            action="bull_put_execute",
            strategy_id="paper_bull_put_v1",
            entity_id="spread-2",
        ),
        request_payload={"symbol": "QQQ.US", "confirm_paper_order": True},
    )
    ledger.mark_action_submitting(parent.intent.id)

    children = []
    for index, leg in enumerate(("long_entry", "short_entry"), start=1):
        child = ledger.prepare_intent(
            external_account_id="LBPT10087357",
            broker=BrokerName.LONGBRIDGE,
            mode=ExecutionMode.PAPER,
            idempotency_key=f"bull-put-child-{index:04d}",
            request_hash=str(index) * 64,
            operation=TradingOperation.SUBMIT,
            action_context=TradingActionContext(
                action="bull_put_entry",
                strategy_id="paper_bull_put_v1",
                entity_id="spread-2",
                leg=leg,
            ),
            broker_marker=f"st:{index:016d}",
            request_payload={"symbol": f"QQQ-option-{index}", "quantity": 1},
            parent_action_intent_id=parent.intent.id,
        )
        snapshot = remote_snapshot().model_copy(
            update={
                "external_order_id": f"external-order-{index}",
                "symbol": f"QQQ-option-{index}",
            }
        )
        order = local_order(child.intent.id).model_copy(
            update={
                "id": f"order-{index}",
                "client_order_id": f"local-order-{index}",
                "external_order_id": f"external-order-{index}",
                "symbol": f"QQQ-option-{index}",
            }
        )
        ledger.mark_submitting(child.intent.id)
        ledger.mark_broker_acknowledged(child.intent.id, snapshot)
        ledger.persist_broker_result(
            intent_id=child.intent.id,
            order=order,
            snapshot=snapshot,
            audit_event=None,
            create_order=True,
        )
        children.append(child.intent)

        current_parent = ledger.get_action(parent.intent.id)
        assert current_parent is not None
        assert current_parent.state == TradingIntentState.SUBMITTING
        assert current_parent.response_payload is None

    assert {child.trade_action_intent_id for child in children} == {parent.intent.id}
    assert session.scalar(select(func.count()).select_from(TradeActionIntentRecord)) == 1
    assert session.scalar(select(func.count()).select_from(OrderIntentRecord)) == 2
    assert ledger.has_unresolved_intents(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    ) is True
    assert ledger.has_unresolved_intents(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        exclude_action_intent_id=parent.intent.id,
    ) is False

    completed = ledger.complete_action(
        parent.intent.id,
        {"spread_id": "spread-2", "status": "open"},
    )

    assert completed.state == TradingIntentState.PERSISTED
    assert completed.response_payload == {"spread_id": "spread-2", "status": "open"}
    assert ledger.has_unresolved_intents(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    ) is False


def test_external_order_lookup_is_scoped_by_broker_and_execution_mode(session: Session) -> None:
    repository = SQLAlchemyOrderRepository(session, attach_intent_ledger=False)
    paper = local_order("intent-paper").model_copy(
        update={"id": "paper-order", "order_intent_id": None}
    )
    live = paper.model_copy(
        update={
            "id": "live-order",
            "client_order_id": "live-local-order-1",
            "mode": ExecutionMode.LIVE,
        }
    )
    repository.create_order(paper)
    repository.create_order(live)

    assert repository.get_by_external_order_id(
        "external-order-1",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
    ).id == "paper-order"
    assert repository.get_by_external_order_id(
        "external-order-1",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.LIVE,
    ).id == "live-order"


def test_no_order_resolution_requires_three_zero_matches_spanning_sixty_seconds(
    session: Session,
    monkeypatch,
) -> None:
    import stocks_tool.repositories.sqlalchemy_trading_intent_ledger as ledger_module

    ledger = SQLAlchemyTradingIntentLedger(session)
    prepared = prepare(ledger, key="strategy-order-key-0002")
    ledger.mark_submitting(prepared.intent.id)

    class FakeDateTime(datetime):
        current = NOW

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(ledger_module, "datetime", FakeDateTime)
    ledger.record_reconciliation_attempt(
        prepared.intent.id,
        "zero matches",
        zero_match=True,
        reconciliation_coverage_start_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
        reconciliation_coverage_end_at=datetime(2100, 1, 1, tzinfo=timezone.utc),
    )
    FakeDateTime.current = NOW + timedelta(seconds=30)
    ledger.record_reconciliation_attempt(
        prepared.intent.id,
        "zero matches",
        zero_match=True,
        reconciliation_coverage_start_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
        reconciliation_coverage_end_at=datetime(2100, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="three successful"):
        ledger.resolve_no_order(prepared.intent.id, actor="local_operator")

    FakeDateTime.current = NOW + timedelta(seconds=61)
    ledger.record_reconciliation_attempt(
        prepared.intent.id,
        "zero matches",
        zero_match=True,
        reconciliation_coverage_start_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
        reconciliation_coverage_end_at=datetime(2100, 1, 1, tzinfo=timezone.utc),
    )
    resolved = ledger.resolve_no_order(
        prepared.intent.id,
        actor="local_operator",
        note="three checks complete",
    )

    assert resolved.state == TradingIntentState.RESOLVED_NO_ORDER
    assert resolved.reconciliation_attempts == 3
    assert resolved.response_payload["actor"] == "local_operator"


def test_no_order_resolution_rejects_legacy_zero_match_counts_without_coverage(
    session: Session,
) -> None:
    ledger = SQLAlchemyTradingIntentLedger(session)
    prepared = prepare(ledger, key="strategy-order-key-legacy-coverage")
    ledger.mark_submitting(prepared.intent.id)
    record = session.get(OrderIntentRecord, prepared.intent.id)
    assert record is not None
    record.reconciliation_attempts = 3
    record.first_reconciled_at = NOW
    record.last_reconciled_at = NOW + timedelta(seconds=61)
    session.commit()

    with pytest.raises(ValueError, match="coverage"):
        ledger.resolve_no_order(prepared.intent.id, actor="local_operator")

    ledger.record_reconciliation_attempt(
        prepared.intent.id,
        "complete history still shows zero matches",
        zero_match=True,
        **coverage_kwargs(),
    )
    refreshed = ledger.get_intent(prepared.intent.id)
    assert refreshed is not None
    assert refreshed.reconciliation_attempts == 1


def test_non_zero_reconciliation_invalidates_prior_no_order_evidence(
    session: Session,
    monkeypatch,
) -> None:
    import stocks_tool.repositories.sqlalchemy_trading_intent_ledger as ledger_module

    ledger = SQLAlchemyTradingIntentLedger(session)
    prepared = prepare(ledger, key="strategy-order-key-invalidated-evidence")
    ledger.mark_submitting(prepared.intent.id)

    class FakeDateTime(datetime):
        current = NOW

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(ledger_module, "datetime", FakeDateTime)
    for offset in (0, 30, 61):
        FakeDateTime.current = NOW + timedelta(seconds=offset)
        ledger.record_reconciliation_attempt(
            prepared.intent.id,
            "zero matches",
            zero_match=True,
            **coverage_kwargs(),
        )

    ledger.record_reconciliation_attempt(
        prepared.intent.id,
        "broker marker fingerprint conflict",
        zero_match=False,
    )
    invalidated = ledger.get_intent(prepared.intent.id)
    assert invalidated is not None
    assert invalidated.reconciliation_attempts == 0
    assert invalidated.reconciliation_coverage_start_at is None
    assert invalidated.reconciliation_coverage_end_at is None
    with pytest.raises(ValueError, match="three successful"):
        ledger.resolve_no_order(prepared.intent.id, actor="local_operator")


def test_resolved_no_order_is_terminal_and_known_external_id_cannot_be_resolved(
    session: Session,
    monkeypatch,
) -> None:
    import stocks_tool.repositories.sqlalchemy_trading_intent_ledger as ledger_module

    ledger = SQLAlchemyTradingIntentLedger(session)
    prepared = prepare(ledger, key="strategy-order-key-0004")
    ledger.mark_submitting(prepared.intent.id)

    class FakeDateTime(datetime):
        current = NOW

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(ledger_module, "datetime", FakeDateTime)
    for offset in (0, 30, 61):
        FakeDateTime.current = NOW + timedelta(seconds=offset)
        ledger.record_reconciliation_attempt(
            prepared.intent.id,
            "zero matches",
            zero_match=True,
            **coverage_kwargs(),
        )
    resolved = ledger.resolve_no_order(prepared.intent.id, actor="local_operator")
    after_failure = ledger.record_reconciliation_attempt(
        resolved.id,
        "history temporarily unavailable",
        zero_match=False,
    )
    assert after_failure.state == TradingIntentState.RESOLVED_NO_ORDER

    second = prepare(ledger, key="strategy-order-key-0005")
    ledger.mark_submitting(second.intent.id)
    ledger.mark_broker_acknowledged(second.intent.id, remote_snapshot())
    for offset in (0, 30, 61):
        FakeDateTime.current = NOW + timedelta(seconds=offset)
        ledger.record_reconciliation_attempt(
            second.intent.id,
            "zero matches",
            zero_match=True,
            **coverage_kwargs(),
        )
    with pytest.raises(ValueError, match="external order id"):
        ledger.resolve_no_order(second.intent.id, actor="local_operator")


def test_read_model_policy_matches_ledger_for_known_external_order_id(
    session: Session,
) -> None:
    ledger = SQLAlchemyTradingIntentLedger(session)
    prepared = prepare(ledger, key="strategy-order-key-policy-external-id")
    ledger.mark_submitting(prepared.intent.id)
    ledger.mark_unknown(
        prepared.intent.id,
        "mutation outcome unknown",
        external_order_id="external-order-known",
    )
    record = session.get(OrderIntentRecord, prepared.intent.id)
    assert record is not None
    record.reconciliation_attempts = 3
    record.first_reconciled_at = NOW
    record.last_reconciled_at = NOW + timedelta(seconds=61)
    record.reconciliation_coverage_start_at = COVERAGE_START
    record.reconciliation_coverage_end_at = COVERAGE_END
    session.commit()

    intent = ledger.get_intent(prepared.intent.id)
    action = ledger.get_action(prepared.intent.trade_action_intent_id)
    assert intent is not None
    assert action is not None
    policy = evaluate_no_order_resolution(intent, action)

    assert policy.eligible is False
    assert policy.reason_code == "external_order_id_present"
    with pytest.raises(ValueError, match="external order id"):
        ledger.resolve_no_order(prepared.intent.id, actor="local_operator")


def test_read_model_policy_matches_ledger_for_persisted_composite_parent(
    session: Session,
) -> None:
    ledger = SQLAlchemyTradingIntentLedger(session)
    parent = ledger.prepare_action(
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        idempotency_key="policy-parent-0001",
        request_hash="c" * 64,
        action_context=TradingActionContext(
            action="bull_put_execute",
            strategy_id="paper_bull_put_v1",
            entity_id="policy-spread-1",
        ),
        request_payload={"symbol": "QQQ.US"},
    )
    child = ledger.prepare_intent(
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        idempotency_key="policy-child-0001",
        request_hash="d" * 64,
        operation=TradingOperation.SUBMIT,
        action_context=TradingActionContext(
            action="bull_put_entry",
            strategy_id="paper_bull_put_v1",
            entity_id="policy-spread-1",
            leg="long_entry",
        ),
        broker_marker="st:7777777777777777",
        request_payload={"symbol": "QQQ-option", "quantity": 1},
        parent_action_intent_id=parent.intent.id,
    )
    ledger.mark_submitting(child.intent.id)
    record = session.get(OrderIntentRecord, child.intent.id)
    parent_record = session.get(TradeActionIntentRecord, parent.intent.id)
    assert record is not None
    assert parent_record is not None
    record.reconciliation_attempts = 3
    record.first_reconciled_at = NOW
    record.last_reconciled_at = NOW + timedelta(seconds=61)
    record.reconciliation_coverage_start_at = COVERAGE_START
    record.reconciliation_coverage_end_at = COVERAGE_END
    parent_record.state = TradingIntentState.PERSISTED.value
    session.commit()

    intent = ledger.get_intent(child.intent.id)
    action = ledger.get_action(parent.intent.id)
    assert intent is not None
    assert action is not None
    policy = evaluate_no_order_resolution(intent, action)

    assert policy.eligible is False
    assert policy.reason_code == "parent_action_persisted"
    with pytest.raises(ValueError, match="already persisted"):
        ledger.resolve_no_order(child.intent.id, actor="local_operator")


@pytest.mark.parametrize("operation", [TradingOperation.CANCEL, TradingOperation.REPLACE])
def test_existing_order_mutation_can_be_manually_resolved_when_effect_is_not_observed(
    session: Session,
    monkeypatch,
    operation: TradingOperation,
) -> None:
    import stocks_tool.repositories.sqlalchemy_trading_intent_ledger as ledger_module

    ledger = SQLAlchemyTradingIntentLedger(session)
    prepared = ledger.prepare_intent(
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        idempotency_key=f"existing-order-{operation.value}-0001",
        request_hash="8" * 64,
        operation=operation,
        action_context=TradingActionContext(action=f"order_{operation.value}"),
        broker_marker="st:8888888888888888",
        request_payload={
            "operation": operation.value,
            "external_order_id": "existing-target-order-1",
            "symbol": "UNH.US",
            "side": "buy",
            "quantity": 1,
            "limit_price": "322.00" if operation == TradingOperation.REPLACE else None,
        },
    )
    ledger.mark_submitting(prepared.intent.id)
    ledger.mark_unknown(
        prepared.intent.id,
        "mutation outcome unknown",
        external_order_id="existing-target-order-1",
    )

    class FakeDateTime(datetime):
        current = NOW

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(ledger_module, "datetime", FakeDateTime)
    for offset in (0, 30, 61):
        FakeDateTime.current = NOW + timedelta(seconds=offset)
        ledger.record_reconciliation_attempt(
            prepared.intent.id,
            "target mutation not observed",
            zero_match=True,
            **coverage_kwargs(),
        )

    resolved = ledger.resolve_no_order(
        prepared.intent.id,
        actor="local_operator",
        note="broker history confirms the requested mutation was not observed",
    )

    assert resolved.state == TradingIntentState.RESOLVED_NO_ORDER
    assert resolved.external_order_id == "existing-target-order-1"


def test_resolved_no_order_rejects_late_broker_result_and_emits_critical_audit(
    session: Session,
    monkeypatch,
) -> None:
    import stocks_tool.repositories.sqlalchemy_trading_intent_ledger as ledger_module

    ledger = SQLAlchemyTradingIntentLedger(session)
    prepared = prepare(ledger, key="strategy-order-key-late-0001")
    ledger.mark_submitting(prepared.intent.id)

    class FakeDateTime(datetime):
        current = NOW

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(ledger_module, "datetime", FakeDateTime)
    for offset in (0, 30, 61):
        FakeDateTime.current = NOW + timedelta(seconds=offset)
        ledger.record_reconciliation_attempt(
            prepared.intent.id,
            "zero matches",
            zero_match=True,
            **coverage_kwargs(),
        )
    resolved = ledger.resolve_no_order(
        prepared.intent.id,
        actor="local_operator",
        note="manually confirmed absent",
    )

    with pytest.raises(ValueError, match="terminal.*manual action"):
        ledger.mark_broker_acknowledged(resolved.id, remote_snapshot())

    with pytest.raises(ValueError, match="terminal.*manual action"):
        ledger.persist_broker_result(
            intent_id=resolved.id,
            order=local_order(resolved.id),
            snapshot=remote_snapshot(),
            audit_event=None,
            create_order=True,
        )

    current = ledger.get_intent(resolved.id)
    assert current is not None
    assert current.state == TradingIntentState.RESOLVED_NO_ORDER
    assert current.external_order_id is None
    assert current.response_payload["actor"] == "local_operator"
    action = ledger.get_action(current.trade_action_intent_id)
    assert action is not None
    assert action.state == TradingIntentState.RESOLVED_NO_ORDER
    assert session.scalar(select(func.count()).select_from(OrderRecord)) == 0
    assert session.scalar(select(func.count()).select_from(ExecutionRecord)) == 0
    events = session.execute(
        select(StrategyAuditEventRecord).where(
            StrategyAuditEventRecord.warning_code
            == "late_broker_result_requires_manual_action"
        )
    ).scalars().all()
    assert len(events) == 1
    assert events[0].payload["severity"] == "critical"
    assert events[0].payload["manual_action_required"] is True
    assert events[0].payload["external_order_id"] == "external-order-1"


def test_composite_parent_converges_after_all_children_resolve_no_order(
    session: Session,
    monkeypatch,
) -> None:
    import stocks_tool.repositories.sqlalchemy_trading_intent_ledger as ledger_module

    ledger = SQLAlchemyTradingIntentLedger(session)
    parent_kwargs = {
        "external_account_id": "LBPT10087357",
        "broker": BrokerName.LONGBRIDGE,
        "mode": ExecutionMode.PAPER,
        "idempotency_key": "bull-put-parent-resolve-0001",
        "request_hash": "f" * 64,
        "action_context": TradingActionContext(
            action="bull_put_execute",
            strategy_id="paper_bull_put_v1",
            entity_id="spread-resolve-1",
        ),
        "request_payload": {"symbol": "QQQ.US", "confirm_paper_order": True},
    }
    parent = ledger.prepare_action(**parent_kwargs)
    ledger.mark_action_submitting(parent.intent.id)
    children = []
    for index, leg in enumerate(("long_entry", "short_entry"), start=1):
        children.append(
            ledger.prepare_intent(
                external_account_id="LBPT10087357",
                broker=BrokerName.LONGBRIDGE,
                mode=ExecutionMode.PAPER,
                idempotency_key=f"bull-put-resolve-child-{index:04d}",
                request_hash=str(index) * 64,
                operation=TradingOperation.SUBMIT,
                action_context=TradingActionContext(
                    action="bull_put_entry",
                    strategy_id="paper_bull_put_v1",
                    entity_id="spread-resolve-1",
                    leg=leg,
                ),
                broker_marker=f"st:{index:016d}",
                request_payload={"symbol": f"QQQ-option-{index}", "quantity": 1},
                parent_action_intent_id=parent.intent.id,
            ).intent
        )

    class FakeDateTime(datetime):
        current = NOW

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(ledger_module, "datetime", FakeDateTime)

    for offset in (0, 30, 61):
        FakeDateTime.current = NOW + timedelta(seconds=offset)
        ledger.record_reconciliation_attempt(
            children[0].id,
            "zero matches",
            zero_match=True,
            **coverage_kwargs(),
        )
    ledger.resolve_no_order(children[0].id, actor="local_operator", note="long absent")

    waiting_parent = ledger.get_action(parent.intent.id)
    assert waiting_parent is not None
    assert waiting_parent.state == TradingIntentState.UNKNOWN
    assert ledger.has_unresolved_intents(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    ) is True

    for offset in (120, 150, 181):
        FakeDateTime.current = NOW + timedelta(seconds=offset)
        ledger.record_reconciliation_attempt(
            children[1].id,
            "zero matches",
            zero_match=True,
            **coverage_kwargs(),
        )
    ledger.resolve_no_order(children[1].id, actor="local_operator", note="short absent")

    settled_parent = ledger.get_action(parent.intent.id)
    assert settled_parent is not None
    assert settled_parent.state == TradingIntentState.REJECTED
    assert settled_parent.response_payload["manual_action_required"] is True
    assert settled_parent.response_payload["resolved_child_intent_id"] == children[1].id
    assert {item["state"] for item in settled_parent.response_payload["child_intents"]} == {
        TradingIntentState.RESOLVED_NO_ORDER.value
    }
    assert ledger.has_unresolved_intents(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    ) is False
    event = session.execute(
        select(StrategyAuditEventRecord).where(
            StrategyAuditEventRecord.warning_code
            == "composite_trade_action_manual_resolution_required"
        )
    ).scalar_one()
    assert event.payload["severity"] == "critical"
    assert event.payload["trade_action_intent_id"] == parent.intent.id


def test_composite_parent_converges_when_sibling_persists_after_no_order_resolution(
    session: Session,
    monkeypatch,
) -> None:
    import stocks_tool.repositories.sqlalchemy_trading_intent_ledger as ledger_module

    ledger = SQLAlchemyTradingIntentLedger(session)
    parent = ledger.prepare_action(
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        idempotency_key="bull-put-parent-resolve-0002",
        request_hash="9" * 64,
        action_context=TradingActionContext(
            action="bull_put_execute",
            strategy_id="paper_bull_put_v1",
            entity_id="spread-resolve-2",
        ),
        request_payload={"symbol": "QQQ.US", "confirm_paper_order": True},
    )
    ledger.mark_action_submitting(parent.intent.id)
    children = []
    for index, leg in enumerate(("long_entry", "short_entry"), start=1):
        children.append(
            ledger.prepare_intent(
                external_account_id="LBPT10087357",
                broker=BrokerName.LONGBRIDGE,
                mode=ExecutionMode.PAPER,
                idempotency_key=f"bull-put-mixed-child-{index:04d}",
                request_hash=str(index + 3) * 64,
                operation=TradingOperation.SUBMIT,
                action_context=TradingActionContext(
                    action="bull_put_entry",
                    strategy_id="paper_bull_put_v1",
                    entity_id="spread-resolve-2",
                    leg=leg,
                ),
                broker_marker=f"st:{index + 20:016d}",
                request_payload={"symbol": f"QQQ-mixed-option-{index}", "quantity": 1},
                parent_action_intent_id=parent.intent.id,
            ).intent
        )

    class FakeDateTime(datetime):
        current = NOW

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(ledger_module, "datetime", FakeDateTime)
    for offset in (0, 30, 61):
        FakeDateTime.current = NOW + timedelta(seconds=offset)
        ledger.record_reconciliation_attempt(
            children[0].id,
            "zero matches",
            zero_match=True,
            **coverage_kwargs(),
        )
    ledger.resolve_no_order(children[0].id, actor="local_operator", note="long absent")

    assert ledger.get_action(parent.intent.id).state == TradingIntentState.UNKNOWN

    second_snapshot = remote_snapshot().model_copy(
        update={
            "external_order_id": "external-mixed-order-2",
            "symbol": "QQQ-mixed-option-2",
        }
    )
    second_order = local_order(children[1].id).model_copy(
        update={
            "id": "mixed-order-2",
            "client_order_id": "mixed-local-order-2",
            "external_order_id": "external-mixed-order-2",
            "symbol": "QQQ-mixed-option-2",
        }
    )
    ledger.mark_submitting(children[1].id)
    ledger.mark_broker_acknowledged(children[1].id, second_snapshot)
    ledger.persist_broker_result(
        intent_id=children[1].id,
        order=second_order,
        snapshot=second_snapshot,
        audit_event=None,
        create_order=True,
        reconciled=True,
    )

    settled_parent = ledger.get_action(parent.intent.id)
    assert settled_parent is not None
    assert settled_parent.state == TradingIntentState.REJECTED
    assert settled_parent.response_payload["resolved_child_intent_id"] == children[0].id
    assert {item["state"] for item in settled_parent.response_payload["child_intents"]} == {
        TradingIntentState.RESOLVED_NO_ORDER.value,
        TradingIntentState.PERSISTED.value,
    }
    assert ledger.has_unresolved_intents(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    ) is False
    assert session.scalar(select(func.count()).select_from(OrderRecord)) == 1
    assert session.scalar(select(func.count()).select_from(ExecutionRecord)) == 1


@pytest.mark.parametrize("failure_stage", ["order", "execution", "audit"])
def test_persistence_failure_rolls_back_order_execution_and_audit(
    session: Session,
    monkeypatch,
    failure_stage: str,
) -> None:
    from stocks_tool.repositories.sqlalchemy_strategy_audit_event_repository import (
        SQLAlchemyStrategyAuditEventRepository,
    )

    ledger = SQLAlchemyTradingIntentLedger(session)
    prepared = prepare(ledger, key="strategy-order-key-0003")
    ledger.mark_submitting(prepared.intent.id)
    ledger.mark_broker_acknowledged(prepared.intent.id, remote_snapshot())
    if failure_stage == "order":
        monkeypatch.setattr(
            SQLAlchemyOrderRepository,
            "_apply_order",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("order insert failed")),
        )
    elif failure_stage == "execution":
        monkeypatch.setattr(
            SQLAlchemyTradingIntentLedger,
            "_upsert_execution",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("execution insert failed")
            ),
        )
    else:
        monkeypatch.setattr(
            SQLAlchemyStrategyAuditEventRepository,
            "_apply_request",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("audit insert failed")),
        )

    with pytest.raises(RuntimeError, match=f"{failure_stage} insert failed"):
        ledger.persist_broker_result(
            intent_id=prepared.intent.id,
            order=local_order(prepared.intent.id).model_copy(update={"id": "order-3"}),
            snapshot=remote_snapshot().model_copy(update={"external_order_id": "external-order-3"}),
            audit_event=CreateStrategyAuditEventRequest(
                external_account_id="LBPT10087357",
                mode=ExecutionMode.PAPER,
                action="paper_order_submitted",
            ),
            create_order=True,
        )

    assert session.scalar(select(func.count()).select_from(OrderRecord)) == 0
    assert session.scalar(select(func.count()).select_from(ExecutionRecord)) == 0
    assert session.scalar(select(func.count()).select_from(StrategyAuditEventRecord)) == 0
    assert ledger.get_intent(prepared.intent.id).state == TradingIntentState.BROKER_ACKNOWLEDGED


def test_bull_put_spread_compare_and_swap_increments_version(session: Session) -> None:
    repository = SQLAlchemyBullPutSpreadRepository(session)
    spread = BullPutSpread(
        id="spread-version-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="QQQ.US",
        expiration_date=date(2026, 8, 21),
        contracts=1,
        width=Decimal("2"),
        long_symbol="QQQ260821P448000.US",
        long_strike=Decimal("448"),
        short_symbol="QQQ260821P450000.US",
        short_strike=Decimal("450"),
        status=SpreadStatus.OPEN,
    )
    created = repository.create_spread(spread)

    updated = repository.update_spread(
        created.model_copy(update={"status": SpreadStatus.EXIT_PENDING_SHORT}),
        expected_version=0,
    )

    assert updated.version == 1
    with pytest.raises(ConcurrentSpreadUpdateError, match="expected version 0"):
        repository.update_spread(
            created.model_copy(update={"status": SpreadStatus.CLOSED}),
            expected_version=0,
        )
