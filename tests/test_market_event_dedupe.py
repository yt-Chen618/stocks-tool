from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import threading

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.db.base import Base
from stocks_tool.db.models import MarketEventRecord
from stocks_tool.application.services.market_event_ingestion import MarketEventIngestionService
from stocks_tool.domain.enums import MarketEventType
from stocks_tool.domain.models import CreateMarketEventRequest
from stocks_tool.repositories.sqlalchemy_market_event_repository import (
    SQLAlchemyMarketEventRepository,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


NOW = datetime(2026, 10, 4, 13, 30, tzinfo=timezone.utc)


def event_request(title: str = "UNH earnings") -> CreateMarketEventRequest:
    return CreateMarketEventRequest(
        symbol="unh.us",
        event_type=MarketEventType.EARNINGS,
        title=title,
        scheduled_at=NOW,
    )


def test_new_market_event_dedupe_is_atomic_and_normalized() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            repository = SQLAlchemyMarketEventRepository(session)
            first, created = repository.create_event_if_absent(event_request())
            replay, replay_created = repository.create_event_if_absent(
                event_request("  unh   EARNINGS  ")
            )

            assert created is True
            assert replay_created is False
            assert replay.id == first.id
            assert session.scalar(select(func.count(MarketEventRecord.id))) == 1
    finally:
        engine.dispose()


def test_legacy_rows_without_dedupe_key_are_preserved() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.add(
                MarketEventRecord(
                    id="legacy-event-1",
                    symbol="UNH.US",
                    event_type=MarketEventType.EARNINGS.value,
                    title="UNH earnings",
                    scheduled_at=NOW,
                    dedupe_key=None,
                )
            )
            session.commit()
            repository = SQLAlchemyMarketEventRepository(session)

            event, created = repository.create_event_if_absent(
                event_request("UNH earnings")
            )

            assert created is False
            assert event.id == "legacy-event-1"
            assert session.scalar(select(func.count(MarketEventRecord.id))) == 1
            assert session.scalar(
                select(func.count(MarketEventRecord.id)).where(
                    MarketEventRecord.dedupe_key.is_(None)
                )
            ) == 1
    finally:
        engine.dispose()


def test_ingestion_rerun_skips_equivalent_legacy_event() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.add(
                MarketEventRecord(
                    id="legacy-event-2",
                    symbol="UNH.US",
                    event_type=MarketEventType.EARNINGS.value,
                    title="UNH earnings",
                    scheduled_at=NOW,
                    dedupe_key=None,
                )
            )
            session.commit()
            result = MarketEventIngestionService(
                SQLAlchemyMarketEventRepository(session)
            ).import_events([event_request("  unh   earnings ")])

            assert result.created == 0
            assert result.skipped_duplicates == 1
            assert result.events == []
            assert session.scalar(select(func.count(MarketEventRecord.id))) == 1
    finally:
        engine.dispose()


def test_concurrent_legacy_reuse_returns_stable_existing_row(tmp_path) -> None:
    database_path = tmp_path / "market-events.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.add(
                MarketEventRecord(
                    id="legacy-event-3",
                    symbol="UNH.US",
                    event_type=MarketEventType.EARNINGS.value,
                    title="UNH earnings",
                    scheduled_at=NOW,
                    dedupe_key=None,
                )
            )
            session.commit()
        barrier = threading.Barrier(2)

        def worker() -> tuple[str, bool]:
            worker_engine = create_engine(
                database_url,
                connect_args={"check_same_thread": False},
            )
            try:
                with Session(worker_engine, expire_on_commit=False) as session:
                    barrier.wait(timeout=5)
                    event, created = SQLAlchemyMarketEventRepository(session).create_event_if_absent(
                        event_request("unh earnings")
                    )
                    return event.id, created
            finally:
                worker_engine.dispose()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _index: worker(), range(2)))

        assert outcomes == [("legacy-event-3", False), ("legacy-event-3", False)]
        with Session(engine) as session:
            assert session.scalar(select(func.count(MarketEventRecord.id))) == 1
    finally:
        engine.dispose()


def test_legacy_lookup_keyset_reaches_match_beyond_first_page() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.add_all(
                [
                    MarketEventRecord(
                        id=f"legacy-bulk-{index:04d}",
                        symbol=f"OTHER{index}.US",
                        event_type=MarketEventType.EARNINGS.value,
                        title=f"Other earnings {index}",
                        scheduled_at=NOW,
                        dedupe_key=None,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                    for index in range(500)
                ]
            )
            session.add(
                MarketEventRecord(
                    id="legacy-bulk-target",
                    symbol="TARGET.US",
                    event_type=MarketEventType.EARNINGS.value,
                    title="Target earnings",
                    scheduled_at=NOW,
                    dedupe_key=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.commit()

            event, created = SQLAlchemyMarketEventRepository(session).create_event_if_absent(
                CreateMarketEventRequest(
                    symbol="target.us",
                    event_type=MarketEventType.EARNINGS,
                    title=" target   earnings ",
                    scheduled_at=NOW,
                )
            )

            assert created is False
            assert event.id == "legacy-bulk-target"
            assert session.scalar(select(func.count(MarketEventRecord.id))) == 501
    finally:
        engine.dispose()
