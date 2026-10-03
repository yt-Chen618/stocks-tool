from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.db.base import Base
from stocks_tool.db.models import (
    BrokerAccountRecord,
    ExecutionRecord,
    JournalEntryRecord,
    OrderRecord,
)
from stocks_tool.domain.enums import ExecutionMode, JournalEntryType
from stocks_tool.domain.pagination import encode_cursor
from stocks_tool.domain.models import JournalEntry
from stocks_tool.repositories.sqlalchemy_execution_repository import SQLAlchemyExecutionRepository
from stocks_tool.repositories.sqlalchemy_journal_repository import SQLAlchemyJournalRepository


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


ACCOUNT_ID = "LBPT10087357"
NOW = datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc)


def _repositories() -> tuple[Session, SQLAlchemyExecutionRepository, SQLAlchemyJournalRepository, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            BrokerAccountRecord.__table__,
            OrderRecord.__table__,
            ExecutionRecord.__table__,
            JournalEntryRecord.__table__,
        ],
    )
    session = Session(engine, expire_on_commit=False)
    session.add(
        BrokerAccountRecord(
            id="broker-account-1",
            broker="longbridge",
            external_account_id=ACCOUNT_ID,
            display_name="Paper account",
            base_currency="USD",
        )
    )
    for order_id, mode in (("order-paper", "paper"), ("order-live", "live")):
        session.add(
            OrderRecord(
                id=order_id,
                broker_account_id="broker-account-1",
                broker="longbridge",
                external_order_id=f"external-{order_id}",
                symbol="QQQ.US",
                side="buy",
                quantity=1,
                order_type="limit",
                time_in_force="day",
                execution_mode=mode,
                status="filled",
                executed_quantity=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    session.add_all(
        [
            ExecutionRecord(
                id="execution-paper",
                order_id="order-paper",
                broker="longbridge",
                external_account_id=ACCOUNT_ID,
                external_order_id="external-order-paper",
                external_execution_id="external-execution-paper",
                symbol="QQQ.US",
                side="buy",
                quantity=1,
                executed_at=NOW,
            ),
            ExecutionRecord(
                id="execution-live",
                order_id="order-live",
                broker="longbridge",
                external_account_id=ACCOUNT_ID,
                external_order_id="external-order-live",
                external_execution_id="external-execution-live",
                symbol="QQQ.US",
                side="buy",
                quantity=1,
                executed_at=NOW,
            ),
        ]
    )
    session.add_all(
        [
            JournalEntryRecord(
                id="journal-paper",
                external_account_id=ACCOUNT_ID,
                symbol="QQQ.US",
                entry_type=JournalEntryType.REVIEW.value,
                title="Paper journal",
                notes="paper",
                order_id="order-paper",
                created_at=NOW,
                updated_at=NOW,
            ),
            JournalEntryRecord(
                id="journal-live",
                external_account_id=ACCOUNT_ID,
                symbol="QQQ.US",
                entry_type=JournalEntryType.REVIEW.value,
                title="Live journal",
                notes="live",
                order_id="order-live",
                created_at=NOW,
                updated_at=NOW,
            ),
            JournalEntryRecord(
                id="journal-execution-only",
                external_account_id=ACCOUNT_ID,
                symbol="QQQ.US",
                entry_type=JournalEntryType.REVIEW.value,
                title="Execution linked journal",
                notes="live execution link",
                execution_id="execution-live",
                created_at=NOW,
                updated_at=NOW,
            ),
            JournalEntryRecord(
                id="journal-orderless",
                external_account_id=ACCOUNT_ID,
                symbol="QQQ.US",
                entry_type=JournalEntryType.REVIEW.value,
                title="Orderless legacy journal",
                notes="legacy",
                created_at=NOW,
                updated_at=NOW,
            ),
        ]
    )
    session.commit()
    return session, SQLAlchemyExecutionRepository(session), SQLAlchemyJournalRepository(session), engine


def test_explicit_execution_mode_scopes_linked_order_reads_and_cursor() -> None:
    session, executions, _journals, engine = _repositories()
    try:
        assert [item.id for item in executions.list_executions(external_account_id=ACCOUNT_ID)] == [
            "execution-paper",
            "execution-live",
        ]
        assert [item.id for item in executions.list_executions(external_account_id=ACCOUNT_ID, mode=ExecutionMode.PAPER)] == [
            "execution-paper"
        ]
        assert [item.id for item in executions.list_executions(external_account_id=ACCOUNT_ID, mode=ExecutionMode.LIVE)] == [
            "execution-live"
        ]

        paper_cursor = encode_cursor(
            resource="executions",
            scope={"external_account_id": ACCOUNT_ID, "order_id": None, "mode": "paper"},
            position={"created_at": NOW.isoformat(), "id": "execution-paper"},
        )
        with pytest.raises(ValueError):
            executions.list_executions_page(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.LIVE,
                limit=1,
                cursor=paper_cursor,
            )
    finally:
        session.close()
        engine.dispose()


def test_explicit_journal_mode_requires_linked_order_or_execution_and_preserves_legacy_history() -> None:
    session, _executions, journals, engine = _repositories()
    try:
        assert {item.id for item in journals.list_entries(external_account_id=ACCOUNT_ID)} == {
            "journal-paper",
            "journal-live",
            "journal-execution-only",
            "journal-orderless",
        }
        assert {item.id for item in journals.list_entries(external_account_id=ACCOUNT_ID, mode=ExecutionMode.PAPER)} == {
            "journal-paper"
        }
        assert {item.id for item in journals.list_entries(external_account_id=ACCOUNT_ID, mode=ExecutionMode.LIVE)} == {
            "journal-live",
            "journal-execution-only",
        }

        paper_page = journals.list_entries_page(
            external_account_id=ACCOUNT_ID,
            mode=ExecutionMode.PAPER,
            limit=1,
        )
        assert paper_page.next_cursor is None
    finally:
        session.close()
        engine.dispose()


def test_standalone_journal_mode_roundtrips_into_scoped_history() -> None:
    session, _executions, journals, engine = _repositories()
    try:
        created = journals.create_entry(
            JournalEntry(
                id="journal-new-paper-note",
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
                symbol="QQQ.US",
                entry_type=JournalEntryType.NOTE,
                title="New paper note",
                notes="The explicit mode must survive persistence.",
                created_at=NOW,
                updated_at=NOW,
            )
        )

        assert created.mode is ExecutionMode.PAPER
        paper_ids = {
            item.id
            for item in journals.list_entries(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
            )
        }
        live_ids = {
            item.id
            for item in journals.list_entries(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.LIVE,
            )
        }
        assert "journal-new-paper-note" in paper_ids
        assert "journal-new-paper-note" not in live_ids
    finally:
        session.close()
        engine.dispose()
