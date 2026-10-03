from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.db.base import Base
from stocks_tool.db.models import BullPutSpreadRecord
from stocks_tool.domain.enums import ExecutionMode, SpreadStatus
from stocks_tool.repositories.sqlalchemy_bull_put_spread_repository import (
    SQLAlchemyBullPutSpreadRepository,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


ACCOUNT_ID = "LBPT10087357"
NOW = datetime(2026, 10, 4, 14, 30, tzinfo=timezone.utc)


def _record(
    index: int,
    *,
    status: SpreadStatus,
    closed_at: datetime | None = None,
    manual_action_required: bool = False,
    symbol: str = "QQQ.US",
    entry_started_at: datetime | None = None,
) -> BullPutSpreadRecord:
    return BullPutSpreadRecord(
        id=f"spread-{index}",
        broker="longbridge",
        external_account_id=ACCOUNT_ID,
        strategy_id="paper_bull_put_v1",
        execution_mode=ExecutionMode.PAPER.value,
        underlying_symbol=symbol,
        expiration_date=date(2026, 10, 30),
        contracts=1,
        width=Decimal("3"),
        long_symbol="QQQ261030P500000.US",
        long_strike=Decimal("500"),
        short_symbol="QQQ261030P503000.US",
        short_strike=Decimal("503"),
        status=status.value,
        manual_action_required=manual_action_required,
        entry_started_at=entry_started_at,
        closed_at=closed_at,
        created_at=NOW,
        updated_at=NOW,
    )


def test_bull_put_capacity_and_review_reads_use_sql_aggregates() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.add_all(
                [
                    _record(1, status=SpreadStatus.OPEN, symbol="QQQ.US"),
                    _record(
                        2,
                        status=SpreadStatus.OPEN,
                        symbol="SMH.US",
                        manual_action_required=True,
                    ),
                    _record(
                        3,
                        status=SpreadStatus.CLOSED,
                        closed_at=NOW - timedelta(days=2),
                    ),
                    _record(
                        4,
                        status=SpreadStatus.CLOSED,
                        closed_at=NOW - timedelta(hours=1),
                    ),
                ]
            )
            session.commit()
            repository = SQLAlchemyBullPutSpreadRepository(session)

            assert repository.count_spreads(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
                statuses=(SpreadStatus.OPEN,),
            ) == 2
            assert repository.count_spreads(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
                manual_action_required=True,
            ) == 1
            oldest_closed_at = repository.get_oldest_closed_at(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
            )
            assert oldest_closed_at is not None
            assert oldest_closed_at.replace(tzinfo=timezone.utc) == NOW - timedelta(days=2)
            recent = repository.list_closed_spreads_since(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
                closed_since=NOW - timedelta(days=1),
            )
            assert [spread.id for spread in recent] == ["spread-4"]
    finally:
        engine.dispose()
