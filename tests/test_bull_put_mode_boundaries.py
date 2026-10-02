from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.db.base import Base
from stocks_tool.db.models import BrokerAccountRecord, BullPutSpreadRecord
from stocks_tool.domain.enums import BrokerName, ExecutionMode, SpreadStatus
from stocks_tool.domain.models import BullPutStrategyRuntimeState
from stocks_tool.repositories.sqlalchemy_bull_put_spread_repository import (
    SQLAlchemyBullPutSpreadRepository,
)
from stocks_tool.application.services.bull_put_strategy import BullPutStrategyService

from tests.test_bull_put_strategy import build_open_spread, build_service


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


def _build_service_with_mixed_spreads(*, closed: bool = False) -> tuple[object, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    session.add(
        BrokerAccountRecord(
            id="broker-account-1",
            broker=BrokerName.LONGBRIDGE.value,
            external_account_id="LBPT10087357",
            display_name="Longbridge Paper",
            base_currency="USD",
            options_level="Level 2",
        )
    )
    session.commit()
    repository = SQLAlchemyBullPutSpreadRepository(session)
    base_updates = (
        {
            "status": SpreadStatus.CLOSED,
            "closed_at": datetime(2026, 6, 20, 14, 45, tzinfo=timezone.utc),
            "raw_payload": {"close": {"realized_pnl": "80.00"}},
        }
        if closed
        else {"status": SpreadStatus.OPEN}
    )
    paper = build_open_spread().model_copy(
        update={"id": "paper-spread", "mode": ExecutionMode.PAPER, **base_updates}
    )
    live = build_open_spread().model_copy(
        update={"id": "live-spread", "mode": ExecutionMode.LIVE, **base_updates}
    )
    for spread in (paper, live):
        record = BullPutSpreadRecord(id=spread.id)
        with session.no_autoflush:
            repository._apply_spread(record, spread)
        record.version = spread.version
        session.add(record)
    session.commit()
    service, _, _, _ = build_service()
    service.spreads = repository
    return service, engine


def test_bull_put_mode_and_status_filters_are_database_scoped() -> None:
    service, engine = _build_service_with_mixed_spreads()
    try:
        paper_spreads = service.list_spreads(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            statuses={SpreadStatus.OPEN},
        )
        live_spreads = service.list_spreads(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.LIVE,
            statuses={SpreadStatus.OPEN},
        )

        assert [spread.id for spread in paper_spreads] == ["paper-spread"]
        assert [spread.id for spread in live_spreads] == ["live-spread"]
    finally:
        engine.dispose()


def test_paper_entry_capacity_ignores_live_spreads() -> None:
    service, engine = _build_service_with_mixed_spreads()
    try:
        service.settings.bull_put_strategy.account_max_open_spreads = 2
        state = BullPutStrategyRuntimeState(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            current_session_date=date(2026, 5, 22),
        )

        try:
            service._assert_entry_capacity(
                external_account_id="LBPT10087357",
                symbol="EWY.US",
                runtime_state=state,
            )
        except ValueError as exc:
            raise AssertionError("A live spread must not consume paper entry capacity.") from exc
    finally:
        engine.dispose()


def test_runtime_projection_counts_only_spreads_in_state_mode() -> None:
    service, engine = _build_service_with_mixed_spreads()
    try:
        state = BullPutStrategyRuntimeState(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            current_session_date=date(2026, 5, 22),
        )
        computed = service._with_runtime_computed_fields(
            state,
            as_of=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
        )

        assert computed.active_spread_count == 1
        assert computed.open_spread_count == 1
    finally:
        engine.dispose()


def test_bull_put_review_uses_requested_mode_for_closed_history() -> None:
    service, engine = _build_service_with_mixed_spreads(closed=True)
    try:
        service.journal_service.create_entry.return_value = None
        result = service.run_review(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            as_of=datetime(2026, 6, 22, 14, 45, tzinfo=timezone.utc),
            force=True,
        )

        assert result.reviewed_spread_ids == ["paper-spread"]
    finally:
        engine.dispose()
