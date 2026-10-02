from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.application.services.strategy_lifecycle import BULL_PUT_CLOSE_ORDER_WARNING
from stocks_tool.db.base import Base
from stocks_tool.db.models import BrokerAccountRecord, BullPutSpreadRecord
from stocks_tool.domain.enums import BrokerName, ExecutionMode, SpreadStatus
from stocks_tool.domain.models import BullPutSpread
from stocks_tool.repositories.sqlalchemy_bull_put_spread_repository import SQLAlchemyBullPutSpreadRepository


NOW = datetime(2026, 6, 15, 14, 45, tzinfo=timezone.utc)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


def _spread(**updates) -> BullPutSpread:
    return BullPutSpread(
        id="spread-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="QQQ.US",
        expiration_date=date(2026, 6, 19),
        contracts=1,
        width=Decimal("2"),
        long_symbol="QQQ260619P448000.US",
        long_strike=Decimal("448"),
        short_symbol="QQQ260619P450000.US",
        short_strike=Decimal("450"),
        status=SpreadStatus.OPEN,
        short_exit_order_id="short-exit",
        created_at=NOW,
        updated_at=NOW,
        **updates,
    )


def test_bull_put_spread_repository_maps_lifecycle_summary_from_raw_payload(monkeypatch) -> None:
    repo = SQLAlchemyBullPutSpreadRepository(Mock())
    monkeypatch.setattr(
        SQLAlchemyBullPutSpreadRepository,
        "_resolve_broker_account_id",
        staticmethod(lambda session, spread: "broker-account-1"),
    )
    next_monitor_after = datetime(2026, 6, 15, 14, 50, tzinfo=timezone.utc)
    spread = _spread(
        raw_payload={
            "monitor": {
                "should_close": True,
                "next_monitor_after": next_monitor_after.isoformat(),
            },
            "lifecycle": {
                "warning": BULL_PUT_CLOSE_ORDER_WARNING,
                "manual_action_required": True,
                "close_order_state": "CANCELED",
            },
        }
    )
    record = BullPutSpreadRecord(id=spread.id)

    repo._apply_spread(record, spread)
    record.created_at = NOW
    record.updated_at = NOW
    domain = repo._to_domain(record)

    assert record.lifecycle_warning_code == BULL_PUT_CLOSE_ORDER_WARNING
    assert record.manual_action_required is True
    assert record.latest_monitor_should_close is True
    assert record.latest_close_order_status == "canceled"
    assert record.next_monitor_after == next_monitor_after
    assert domain.lifecycle_warning_code == BULL_PUT_CLOSE_ORDER_WARNING
    assert domain.manual_action_required is True
    assert domain.latest_monitor_should_close is True
    assert domain.latest_close_order_status == "canceled"
    assert domain.next_monitor_after == next_monitor_after


def test_bull_put_spread_repository_preserves_explicit_lifecycle_fields_without_raw_payload(monkeypatch) -> None:
    repo = SQLAlchemyBullPutSpreadRepository(Mock())
    monkeypatch.setattr(
        SQLAlchemyBullPutSpreadRepository,
        "_resolve_broker_account_id",
        staticmethod(lambda session, spread: "broker-account-1"),
    )
    spread = _spread(
        raw_payload=None,
        lifecycle_warning_code=BULL_PUT_CLOSE_ORDER_WARNING,
        manual_action_required=True,
        latest_monitor_should_close=True,
        latest_close_order_status="canceled",
        next_monitor_after=NOW,
    )
    record = BullPutSpreadRecord(id=spread.id)

    repo._apply_spread(record, spread)

    assert record.lifecycle_warning_code == BULL_PUT_CLOSE_ORDER_WARNING
    assert record.manual_action_required is True
    assert record.latest_monitor_should_close is True
    assert record.latest_close_order_status == "canceled"
    assert record.next_monitor_after == NOW


def test_bull_put_spread_repository_rolls_back_list_failure() -> None:
    session = Mock()
    session.execute.side_effect = RuntimeError("spread read unavailable")
    repository = SQLAlchemyBullPutSpreadRepository(session)

    try:
        repository.list_spreads(external_account_id="LBPT10087357", status=SpreadStatus.OPEN)
    except RuntimeError as exc:
        assert str(exc) == "spread read unavailable"
    else:
        raise AssertionError("Expected list_spreads to re-raise the database failure.")

    session.rollback.assert_called_once()


def test_active_spread_query_is_database_filtered_and_keeps_rollback_failed() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.add(
                BrokerAccountRecord(
                    id="broker-account-1",
                    broker=BrokerName.LONGBRIDGE.value,
                    external_account_id="LBPT10087357",
                )
            )
            for index, state in enumerate(
                (SpreadStatus.OPEN, SpreadStatus.CLOSED, SpreadStatus.ROLLBACK_FAILED)
            ):
                session.add(
                    BullPutSpreadRecord(
                        id=f"spread-{index}",
                        broker_account_id="broker-account-1",
                        broker=BrokerName.LONGBRIDGE.value,
                        external_account_id="LBPT10087357",
                        strategy_id="paper_bull_put_v1",
                        execution_mode=ExecutionMode.PAPER.value,
                        underlying_symbol="QQQ.US",
                        expiration_date=date(2026, 10, 9),
                        contracts=1,
                        width=Decimal("3"),
                        long_symbol="QQQ261009P500000.US",
                        long_strike=Decimal("500"),
                        short_symbol="QQQ261009P503000.US",
                        short_strike=Decimal("503"),
                        status=state.value,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
            session.commit()

            spreads = SQLAlchemyBullPutSpreadRepository(session).list_spreads(
                external_account_id="LBPT10087357",
                mode=ExecutionMode.PAPER,
                statuses={
                    SpreadStatus.ENTRY_PENDING_LONG,
                    SpreadStatus.ENTRY_PENDING_SHORT,
                    SpreadStatus.OPEN,
                    SpreadStatus.EXIT_PENDING_SHORT,
                    SpreadStatus.EXIT_PENDING_LONG,
                    SpreadStatus.ROLLBACK_FAILED,
                },
            )

            assert {spread.status for spread in spreads} == {
                SpreadStatus.OPEN,
                SpreadStatus.ROLLBACK_FAILED,
            }
    finally:
        engine.dispose()


def _history_record(
    *,
    spread_id: str,
    account_id: str,
    mode: ExecutionMode,
    status: SpreadStatus,
    created_at: datetime,
    manual_action_required: bool = False,
) -> BullPutSpreadRecord:
    return BullPutSpreadRecord(
        id=spread_id,
        broker_account_id=f"broker-{account_id}",
        broker=BrokerName.LONGBRIDGE.value,
        external_account_id=account_id,
        strategy_id="paper_bull_put_v1",
        execution_mode=mode.value,
        underlying_symbol="QQQ.US",
        expiration_date=date(2026, 10, 9),
        contracts=1,
        width=Decimal("3"),
        long_symbol="QQQ261009P500000.US",
        long_strike=Decimal("500"),
        short_symbol="QQQ261009P503000.US",
        short_strike=Decimal("503"),
        status=status.value,
        manual_action_required=manual_action_required,
        created_at=created_at,
        updated_at=created_at,
    )


def test_bull_put_spread_history_page_is_keyset_scoped_and_preserves_detail_reads() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            for account_id in ("LBPT10087357", "other-account"):
                session.add(
                    BrokerAccountRecord(
                        id=f"broker-{account_id}",
                        broker=BrokerName.LONGBRIDGE.value,
                        external_account_id=account_id,
                    )
                )
            for index in range(5):
                session.add(
                    _history_record(
                        spread_id=f"paper-{index}",
                        account_id="LBPT10087357",
                        mode=ExecutionMode.PAPER,
                        status=SpreadStatus.CLOSED,
                        created_at=NOW.replace(microsecond=index),
                    )
                )
                session.add(
                    _history_record(
                        spread_id=f"live-{index}",
                        account_id="LBPT10087357",
                        mode=ExecutionMode.LIVE,
                        status=SpreadStatus.CLOSED,
                        created_at=NOW.replace(microsecond=index),
                    )
                )
                session.add(
                    _history_record(
                        spread_id=f"other-{index}",
                        account_id="other-account",
                        mode=ExecutionMode.PAPER,
                        status=SpreadStatus.CLOSED,
                        created_at=NOW.replace(microsecond=index),
                    )
                )
            session.commit()

            repository = SQLAlchemyBullPutSpreadRepository(session)
            first = repository.list_spreads_page(
                external_account_id="LBPT10087357",
                mode=ExecutionMode.PAPER,
                limit=2,
            )
            assert first.has_more is True
            assert len(first.items) == 2
            assert first.next_cursor

            second = repository.list_spreads_page(
                external_account_id="LBPT10087357",
                mode=ExecutionMode.PAPER,
                limit=2,
                cursor=first.next_cursor,
            )
            assert len(second.items) == 2
            assert set(item.id for item in first.items).isdisjoint(item.id for item in second.items)

            third = repository.list_spreads_page(
                external_account_id="LBPT10087357",
                mode=ExecutionMode.PAPER,
                limit=2,
                cursor=second.next_cursor,
            )
            assert [item.id for item in third.items] == ["paper-0"]
            assert third.has_more is False

            live = repository.list_spreads_page(
                external_account_id="LBPT10087357",
                mode=ExecutionMode.LIVE,
                limit=10,
            )
            assert {item.id for item in live.items} == {f"live-{index}" for index in range(5)}
            assert repository.get_spread("paper-0") is not None
            assert len(
                repository.list_spreads(
                    external_account_id="LBPT10087357",
                    mode=ExecutionMode.PAPER,
                )
            ) == 5

            try:
                repository.list_spreads_page(
                    external_account_id="LBPT10087357",
                    mode=ExecutionMode.LIVE,
                    limit=2,
                    cursor=first.next_cursor,
                )
            except ValueError as exc:
                assert "does not match" in str(exc)
            else:
                raise AssertionError("Expected a Paper cursor to be rejected for a Live query.")
    finally:
        engine.dispose()


def test_working_spread_query_keeps_active_or_manual_rows_and_excludes_closed_rows() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.add(
                BrokerAccountRecord(
                    id="broker-account-1",
                    broker=BrokerName.LONGBRIDGE.value,
                    external_account_id="LBPT10087357",
                )
            )
            session.add_all(
                [
                    _history_record(
                        spread_id="working-open",
                        account_id="LBPT10087357",
                        mode=ExecutionMode.PAPER,
                        status=SpreadStatus.OPEN,
                        created_at=NOW,
                    ),
                    _history_record(
                        spread_id="working-manual",
                        account_id="LBPT10087357",
                        mode=ExecutionMode.PAPER,
                        status=SpreadStatus.CLOSED,
                        created_at=NOW,
                        manual_action_required=True,
                    ),
                    _history_record(
                        spread_id="closed-clean",
                        account_id="LBPT10087357",
                        mode=ExecutionMode.PAPER,
                        status=SpreadStatus.CLOSED,
                        created_at=NOW,
                    ),
                    _history_record(
                        spread_id="live-manual",
                        account_id="LBPT10087357",
                        mode=ExecutionMode.LIVE,
                        status=SpreadStatus.CLOSED,
                        created_at=NOW,
                        manual_action_required=True,
                    ),
                ]
            )
            session.commit()

            repository = SQLAlchemyBullPutSpreadRepository(session)
            working = repository.list_working_spreads(
                external_account_id="LBPT10087357",
                mode=ExecutionMode.PAPER,
                active_statuses={
                    SpreadStatus.ENTRY_PENDING_LONG,
                    SpreadStatus.ENTRY_PENDING_SHORT,
                    SpreadStatus.OPEN,
                    SpreadStatus.EXIT_PENDING_SHORT,
                    SpreadStatus.EXIT_PENDING_LONG,
                },
            )

            assert {spread.id for spread in working} == {"working-open", "working-manual"}
    finally:
        engine.dispose()
