import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from pydantic import ValidationError

from stocks_tool.db.base import Base
from stocks_tool.domain.enums import AssetType
from stocks_tool.domain.models import (
    AddWatchlistItemRequest,
    CreateWatchlistRequest,
    UpdateWatchlistItemRequest,
    UpdateWatchlistRequest,
)
from stocks_tool.db.models import WatchlistItemRecord
from stocks_tool.ports.repository import WatchlistItemConflictError
from stocks_tool.repositories.sqlalchemy_watchlist_repository import SQLAlchemyWatchlistRepository


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


def test_watchlist_repository_update_notes_default_and_delete() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            repository = SQLAlchemyWatchlistRepository(session)
            first = repository.create_watchlist(
                CreateWatchlistRequest(name="First", is_default=True)
            )
            second = repository.create_watchlist(
                CreateWatchlistRequest(name="  Second  ", is_default=True)
            )
            assert second.name == "Second"
            assert repository.get_watchlist(first.id).is_default is False
            second = repository.add_item(
                second.id,
                AddWatchlistItemRequest(symbol="qqq.us", asset_type=AssetType.ETF),
            )
            item_id = second.items[0].id

            updated = repository.update_watchlist(
                second.id,
                UpdateWatchlistRequest(name="Research", description="Main", is_default=True),
            )
            with_notes = repository.update_item(
                second.id,
                item_id,
                UpdateWatchlistItemRequest(notes="Wait for event"),
            )
            deleted = repository.delete_item(second.id, item_id)

            assert updated.name == "Research"
            assert updated.is_default is True
            assert repository.get_watchlist(first.id).is_default is False
            assert with_notes.items[0].notes == "Wait for event"
            assert deleted is True
            assert repository.get_watchlist(second.id).items == []
    finally:
        engine.dispose()


def test_watchlist_item_symbol_is_normalized_and_duplicate_is_a_conflict() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            repository = SQLAlchemyWatchlistRepository(session)
            watchlist = repository.create_watchlist(CreateWatchlistRequest(name="Research"))

            added = repository.add_item(
                watchlist.id,
                AddWatchlistItemRequest(symbol=" qqq.us ", asset_type=AssetType.ETF),
            )

            assert added is not None
            assert [item.symbol for item in added.items] == ["QQQ.US"]
            with pytest.raises(WatchlistItemConflictError):
                repository.add_item(
                    watchlist.id,
                    AddWatchlistItemRequest(symbol="QQQ.US", asset_type=AssetType.ETF),
                )
            assert len(session.execute(select(WatchlistItemRecord)).scalars().all()) == 1
    finally:
        engine.dispose()


def test_watchlist_item_symbol_rejects_blank_input() -> None:
    with pytest.raises(ValidationError):
        AddWatchlistItemRequest(symbol="   ", asset_type=AssetType.STOCK)


def test_watchlist_read_keeps_historical_symbol_text_unchanged() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            repository = SQLAlchemyWatchlistRepository(session)
            watchlist = repository.create_watchlist(CreateWatchlistRequest(name="Research"))
            session.add(
                WatchlistItemRecord(
                    watchlist_id=watchlist.id,
                    symbol=" qqq.us ",
                    asset_type=AssetType.ETF.value,
                )
            )
            session.commit()

            loaded = repository.get_watchlist(watchlist.id)

            assert loaded is not None
            assert loaded.items[0].symbol == " qqq.us "
    finally:
        engine.dispose()


def test_watchlist_item_rejects_historical_trimmed_duplicate_without_mutating_rows() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            repository = SQLAlchemyWatchlistRepository(session)
            watchlist = repository.create_watchlist(CreateWatchlistRequest(name="Research"))
            session.add_all(
                [
                    WatchlistItemRecord(
                        watchlist_id=watchlist.id,
                        symbol=" qqq.us ",
                        asset_type=AssetType.ETF.value,
                    ),
                    WatchlistItemRecord(
                        watchlist_id=watchlist.id,
                        symbol="QQQ.US ",
                        asset_type=AssetType.ETF.value,
                    ),
                ]
            )
            session.commit()

            with pytest.raises(WatchlistItemConflictError):
                repository.add_item(
                    watchlist.id,
                    AddWatchlistItemRequest(symbol="QQQ.US", asset_type=AssetType.ETF),
                )

            rows = session.execute(
                select(WatchlistItemRecord)
                .where(WatchlistItemRecord.watchlist_id == watchlist.id)
                .order_by(WatchlistItemRecord.symbol)
            ).scalars().all()
            assert [row.symbol for row in rows] == [" qqq.us ", "QQQ.US "]
    finally:
        engine.dispose()
