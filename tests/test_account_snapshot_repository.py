from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.db.base import Base
from stocks_tool.db.models import (
    AccountSnapshotRecord,
    BrokerAccountRecord,
    PositionSnapshotRecord,
)
from stocks_tool.domain.enums import AccountSnapshotProvenance, BrokerName, ExecutionMode
from stocks_tool.domain.models import AccountSnapshot
from stocks_tool.repositories.sqlalchemy_account_snapshot_repository import (
    SQLAlchemyAccountSnapshotRepository,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


def _snapshot(*, mode: ExecutionMode | None, captured_at: datetime) -> AccountSnapshot:
    return AccountSnapshot(
        broker=BrokerName.LONGBRIDGE,
        account_id="LBPT10087357",
        mode=mode,
        cash_balance=Decimal("1000"),
        net_liquidation=Decimal("1200"),
        buying_power=Decimal("900"),
        captured_at=captured_at,
    )


def test_snapshot_reads_are_mode_and_provenance_scoped() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            BrokerAccountRecord.__table__,
            AccountSnapshotRecord.__table__,
            PositionSnapshotRecord.__table__,
        ],
    )
    session = Session(engine, expire_on_commit=False)
    session.add(
        BrokerAccountRecord(
            id="broker-account-1",
            broker=BrokerName.LONGBRIDGE.value,
            external_account_id="LBPT10087357",
            display_name="Longbridge Paper",
            base_currency="USD",
        )
    )
    session.commit()
    repository = SQLAlchemyAccountSnapshotRepository(session)

    paper_time = datetime(2026, 10, 4, 1, 0, tzinfo=timezone.utc)
    live_time = datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc)
    upload_time = datetime(2026, 10, 4, 3, 0, tzinfo=timezone.utc)
    repository.create_account_snapshot(
        _snapshot(mode=ExecutionMode.PAPER, captured_at=paper_time),
        provenance=AccountSnapshotProvenance.BROKER_SYNC,
    )
    repository.create_account_snapshot(
        _snapshot(mode=ExecutionMode.LIVE, captured_at=live_time),
        provenance=AccountSnapshotProvenance.BROKER_SYNC,
    )
    repository.create_account_snapshot(
        _snapshot(mode=ExecutionMode.PAPER, captured_at=upload_time),
        provenance=AccountSnapshotProvenance.PUBLIC_UPLOAD,
    )

    trusted_paper = repository.get_latest_account_snapshot(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        trusted_only=True,
    )
    untrusted_paper = repository.get_latest_account_snapshot(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        trusted_only=False,
    )
    trusted_live = repository.get_latest_account_snapshot(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.LIVE,
        trusted_only=True,
    )

    assert trusted_paper is not None
    assert trusted_paper.captured_at.replace(tzinfo=timezone.utc) == paper_time
    assert trusted_paper.provenance is AccountSnapshotProvenance.BROKER_SYNC
    assert untrusted_paper is not None
    assert untrusted_paper.captured_at.replace(tzinfo=timezone.utc) == upload_time
    assert untrusted_paper.provenance is AccountSnapshotProvenance.PUBLIC_UPLOAD
    assert trusted_live is not None
    assert trusted_live.captured_at.replace(tzinfo=timezone.utc) == live_time

    history = repository.list_account_snapshots(external_account_id="LBPT10087357")
    assert len(history) == 3
    assert history[0].provenance is AccountSnapshotProvenance.PUBLIC_UPLOAD

    session.close()
    engine.dispose()
