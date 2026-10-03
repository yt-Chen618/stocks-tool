from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.db.base import Base
from stocks_tool.db.models import OrderIntentRecord, TradeActionIntentRecord
from stocks_tool.application.services.orders import OrderService
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import ExecutionMode, TradingIntentState, TradingOperation
from stocks_tool.ports.trading_intent_ledger import ReconciliationCursor
from stocks_tool.repositories.sqlalchemy_trading_intent_ledger import (
    SQLAlchemyTradingIntentLedger,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


ACCOUNT_ID = "LBPT10087357"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _session() -> tuple[Session, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False, autoflush=False), engine


def _seed(session: Session, count: int) -> None:
    session.add(
        TradeActionIntentRecord(
            id="action-1",
            external_account_id=ACCOUNT_ID,
            broker="longbridge",
            execution_mode=ExecutionMode.PAPER.value,
            idempotency_key="action-key-1",
            request_hash="a" * 64,
            action="order_submit",
            state=TradingIntentState.UNKNOWN.value,
            request_payload={"seed": True},
        )
    )
    session.commit()
    for start in range(0, count, 5_000):
        rows = []
        for index in range(start, min(start + 5_000, count)):
            timestamp = BASE_TIME + timedelta(microseconds=index)
            rows.append(
                {
                    "id": f"intent-{index:06d}",
                    "trade_action_intent_id": "action-1",
                    "external_account_id": ACCOUNT_ID,
                    "broker": "longbridge",
                    "execution_mode": ExecutionMode.PAPER.value,
                    "idempotency_key": f"key-{index:06d}",
                    "request_hash": "a" * 64,
                    "operation": TradingOperation.SUBMIT.value,
                    "action": "order_submit",
                    "broker_marker": f"st:{index:016x}",
                    "state": TradingIntentState.UNKNOWN.value,
                    "request_payload": {"index": index},
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
            )
        session.execute(OrderIntentRecord.__table__.insert(), rows)
    session.commit()


def _page(
    ledger: SQLAlchemyTradingIntentLedger,
    highwater: ReconciliationCursor,
    cursor: ReconciliationCursor | None = None,
    *,
    limit: int = 100,
):
    return ledger.list_reconciliation_intents(
        external_account_id=ACCOUNT_ID,
        mode=ExecutionMode.PAPER,
        states=(TradingIntentState.UNKNOWN,),
        high_watermark=highwater,
        cursor=cursor,
        limit=limit,
    )


def test_reconciliation_keyset_page_stays_bounded_at_100k_rows() -> None:
    session, engine = _session()
    try:
        _seed(session, 100_000)
        ledger = SQLAlchemyTradingIntentLedger(session)
        highwater = ledger.get_reconciliation_high_watermark(
            external_account_id=ACCOUNT_ID,
            mode=ExecutionMode.PAPER,
            states=(TradingIntentState.UNKNOWN,),
        )
        assert highwater is not None

        first = _page(ledger, highwater)
        assert len(first) == 100
        assert [intent.id for intent in first] == [f"intent-{index:06d}" for index in range(100)]
        plan = session.execute(
            text(
                "EXPLAIN QUERY PLAN "
                "SELECT id FROM order_intents "
                "WHERE external_account_id = :account "
                "AND execution_mode = :mode AND state = :state "
                "ORDER BY updated_at, created_at, id LIMIT 100"
            ),
            {
                "account": ACCOUNT_ID,
                "mode": ExecutionMode.PAPER.value,
                "state": TradingIntentState.UNKNOWN.value,
            },
        ).all()
        assert any("ix_order_intents_reconciliation_fair" in str(row) for row in plan)

        cursor = ReconciliationCursor(
            updated_at=first[-1].updated_at,
            created_at=first[-1].created_at,
            intent_id=first[-1].id,
        )
        deep = _page(ledger, highwater, cursor, limit=100)
        assert len(deep) == 100
        assert deep[0].id == "intent-000100"
        assert {intent.id for intent in first}.isdisjoint(intent.id for intent in deep)
    finally:
        session.close()
        engine.dispose()


def test_reconciliation_rotation_reaches_deferred_intents_after_first_500() -> None:
    session, engine = _session()
    try:
        _seed(session, 600)
        ledger = SQLAlchemyTradingIntentLedger(session)
        highwater = ledger.get_reconciliation_high_watermark(
            external_account_id=ACCOUNT_ID,
            mode=ExecutionMode.PAPER,
            states=(TradingIntentState.UNKNOWN,),
        )
        assert highwater is not None

        selected = []
        cursor = None
        while len(selected) < 500:
            page = _page(ledger, highwater, cursor)
            assert page
            selected.extend(page)
            last = page[-1]
            cursor = ReconciliationCursor(last.updated_at, last.created_at, last.id)

        assert len(selected) == 500
        selected_ids = {intent.id for intent in selected}
        for intent in selected:
            ledger.record_reconciliation_attempt(
                intent.id,
                "no-match test evidence",
                zero_match=False,
            )

        next_highwater = ledger.get_reconciliation_high_watermark(
            external_account_id=ACCOUNT_ID,
            mode=ExecutionMode.PAPER,
            states=(TradingIntentState.UNKNOWN,),
        )
        assert next_highwater is not None
        deferred = _page(ledger, next_highwater, limit=100)
        assert [intent.id for intent in deferred] == [
            f"intent-{index:06d}" for index in range(500, 600)
        ]
        assert selected_ids.isdisjoint(intent.id for intent in deferred)
    finally:
        session.close()
        engine.dispose()


def test_order_service_reconciliation_cycle_is_finite_and_fair() -> None:
    session, engine = _session()
    try:
        _seed(session, 600)
        adapter = Mock()
        adapter.list_today_orders.return_value = []
        adapter.list_history_orders.return_value = []
        ledger = SQLAlchemyTradingIntentLedger(session)
        service = OrderService(
            settings=Settings(),
            broker_accounts=Mock(),
            trade_plans=Mock(),
            orders=Mock(),
            executions=Mock(),
            longbridge_adapter=adapter,
            intent_ledger=ledger,
        )

        first = service.reconcile_unresolved_intents(ACCOUNT_ID)
        second = service.reconcile_unresolved_intents(ACCOUNT_ID)

        assert first.scanned_intents == 500
        assert first.unresolved_intents == 500
        assert any("capped at 500" in warning for warning in first.warnings)
        # The next cycle remains bounded; the repository-level rotation test
        # proves that the deferred tail is selected before refreshed rows.
        assert second.scanned_intents == 500
        assert second.unresolved_intents == 500
        assert any("capped at 500" in warning for warning in second.warnings)
    finally:
        session.close()
        engine.dispose()
