from datetime import datetime, timedelta, timezone

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
from stocks_tool.domain.enums import JournalEntryType
from stocks_tool.repositories.sqlalchemy_execution_repository import (
    SQLAlchemyExecutionRepository,
)
from stocks_tool.repositories.sqlalchemy_journal_repository import (
    SQLAlchemyJournalRepository,
)
from stocks_tool.repositories.sqlalchemy_order_repository import SQLAlchemyOrderRepository


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


ACCOUNT_ID = "LBPT10087357"
BROKER_ACCOUNT_ID = "broker-account-1"
BASE_TIME = datetime(2026, 10, 2, 14, 30, tzinfo=timezone.utc)


@pytest.fixture
def history_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            BrokerAccountRecord(
                id=BROKER_ACCOUNT_ID,
                broker="longbridge",
                external_account_id=ACCOUNT_ID,
            )
        )
        session.commit()
        yield session
    engine.dispose()


def _insert_history(session: Session, count: int = 123) -> None:
    orders: list[OrderRecord] = []
    executions: list[ExecutionRecord] = []
    journals: list[JournalEntryRecord] = []
    for index in range(count):
        # Pairs share a timestamp so the id tie-breaker is exercised.
        created_at = BASE_TIME - timedelta(minutes=index // 2)
        order_id = f"order-{index:04d}"
        execution_id = f"execution-{index:04d}"
        orders.append(
            OrderRecord(
                id=order_id,
                broker_account_id=BROKER_ACCOUNT_ID,
                broker="longbridge",
                symbol="QQQ.US",
                side="buy",
                quantity=1,
                order_type="limit",
                time_in_force="day",
                execution_mode="paper",
                status="filled",
                executed_quantity=1,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        executions.append(
            ExecutionRecord(
                id=execution_id,
                order_id=order_id,
                broker="longbridge",
                external_account_id=ACCOUNT_ID,
                symbol="QQQ.US",
                side="buy",
                quantity=1,
                executed_at=created_at,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        journals.append(
            JournalEntryRecord(
                id=f"journal-{index:04d}",
                external_account_id=ACCOUNT_ID,
                symbol="QQQ.US",
                entry_type=JournalEntryType.NOTE.value,
                title=f"Entry {index}",
                notes="History pagination fixture",
                created_at=created_at,
                updated_at=created_at,
            )
        )
    session.add_all([*orders, *executions, *journals])
    session.commit()


def _collect_pages(fetch, *, limit: int) -> tuple[list[str], list[int]]:
    values: list[str] = []
    page_sizes: list[int] = []
    cursor = None
    while True:
        page = fetch(limit=limit, cursor=cursor)
        page_sizes.append(len(page.items))
        values.extend(item.id for item in page.items)
        if not page.has_more:
            assert page.next_cursor is None
            break
        assert page.next_cursor
        cursor = page.next_cursor
    return values, page_sizes


def test_orders_executions_and_journals_page_without_gaps_or_duplicates(history_session: Session) -> None:
    _insert_history(history_session)
    orders = SQLAlchemyOrderRepository(history_session, attach_intent_ledger=False)
    executions = SQLAlchemyExecutionRepository(history_session)
    journals = SQLAlchemyJournalRepository(history_session)

    order_ids, order_page_sizes = _collect_pages(
        lambda **kwargs: orders.list_orders_page(external_account_id=ACCOUNT_ID, **kwargs),
        limit=17,
    )
    execution_ids, execution_page_sizes = _collect_pages(
        lambda **kwargs: executions.list_executions_page(external_account_id=ACCOUNT_ID, **kwargs),
        limit=17,
    )
    journal_ids, journal_page_sizes = _collect_pages(
        lambda **kwargs: journals.list_entries_page(external_account_id=ACCOUNT_ID, **kwargs),
        limit=17,
    )

    expected_indices = [index for group in range(61) for index in (2 * group + 1, 2 * group)] + [122]
    assert order_ids == [f"order-{index:04d}" for index in expected_indices]
    assert execution_ids == [f"execution-{index:04d}" for index in expected_indices]
    assert journal_ids == [f"journal-{index:04d}" for index in expected_indices]
    assert all(size <= 17 for size in [*order_page_sizes, *execution_page_sizes, *journal_page_sizes])
    assert all(len(values) == len(set(values)) for values in [order_ids, execution_ids, journal_ids])


def test_page_cursor_is_bound_to_its_filter_scope(history_session: Session) -> None:
    _insert_history(history_session, count=3)
    repository = SQLAlchemyOrderRepository(history_session, attach_intent_ledger=False)
    first_page = repository.list_orders_page(external_account_id=ACCOUNT_ID, limit=1)

    assert first_page.next_cursor is not None
    with pytest.raises(ValueError, match="does not match this query"):
        repository.list_orders_page(external_account_id="other-account", limit=1, cursor=first_page.next_cursor)


def test_detail_reads_remain_unbounded_by_page_size(history_session: Session) -> None:
    _insert_history(history_session, count=123)
    repository = SQLAlchemyOrderRepository(history_session, attach_intent_ledger=False)

    detail = repository.get_order("order-0122")

    assert detail is not None
    assert detail.id == "order-0122"


def test_business_time_updates_do_not_change_created_cursor_membership(history_session: Session) -> None:
    _insert_history(history_session, count=40)
    execution_repository = SQLAlchemyExecutionRepository(history_session)
    journal_repository = SQLAlchemyJournalRepository(history_session)

    execution_first = execution_repository.list_executions_page(
        external_account_id=ACCOUNT_ID,
        limit=10,
    )
    journal_first = journal_repository.list_entries_page(
        external_account_id=ACCOUNT_ID,
        limit=10,
    )
    execution_record = history_session.get(ExecutionRecord, execution_first.items[0].id)
    journal_record = history_session.get(JournalEntryRecord, journal_first.items[0].id)
    assert execution_record is not None
    assert journal_record is not None
    execution_record.executed_at = BASE_TIME + timedelta(days=1)
    journal_record.updated_at = BASE_TIME + timedelta(days=1)
    history_session.commit()

    execution_second = execution_repository.list_executions_page(
        external_account_id=ACCOUNT_ID,
        limit=10,
        cursor=execution_first.next_cursor,
    )
    journal_second = journal_repository.list_entries_page(
        external_account_id=ACCOUNT_ID,
        limit=10,
        cursor=journal_first.next_cursor,
    )

    assert not ({item.id for item in execution_first.items} & {item.id for item in execution_second.items})
    assert not ({item.id for item in journal_first.items} & {item.id for item in journal_second.items})
