from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from stocks_tool.db.models import WatchlistItemRecord, WatchlistRecord
from stocks_tool.domain.enums import AssetType
from stocks_tool.domain.models import (
    AddWatchlistItemRequest,
    CreateWatchlistRequest,
    Watchlist,
    WatchlistItem,
)
from stocks_tool.ports.repository import WatchlistRepository


class SQLAlchemyWatchlistRepository(WatchlistRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_watchlist(self, request: CreateWatchlistRequest) -> Watchlist:
        record = WatchlistRecord(
            name=request.name,
            description=request.description,
            is_default=request.is_default,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def list_watchlists(self) -> list[Watchlist]:
        query = (
            select(WatchlistRecord)
            .options(selectinload(WatchlistRecord.items))
            .order_by(WatchlistRecord.created_at.desc())
        )
        records = self.session.execute(query).scalars().unique().all()
        return [self._to_domain(record) for record in records]

    def add_item(self, watchlist_id: str, request: AddWatchlistItemRequest) -> Watchlist | None:
        record = self.session.get(WatchlistRecord, watchlist_id)
        if record is None:
            return None

        item = WatchlistItemRecord(
            watchlist_id=watchlist_id,
            symbol=request.symbol.upper(),
            asset_type=request.asset_type.value,
            notes=request.notes,
        )
        self.session.add(item)
        self.session.commit()

        refreshed = self.session.execute(
            select(WatchlistRecord)
            .options(selectinload(WatchlistRecord.items))
            .where(WatchlistRecord.id == watchlist_id)
        ).scalars().unique().one()
        return self._to_domain(refreshed)

    @staticmethod
    def _to_domain(record: WatchlistRecord) -> Watchlist:
        return Watchlist(
            id=record.id,
            name=record.name,
            description=record.description,
            is_default=record.is_default,
            items=[
                WatchlistItem(
                    id=item.id,
                    symbol=item.symbol,
                    asset_type=AssetType(item.asset_type),
                    notes=item.notes,
                    created_at=item.created_at,
                )
                for item in sorted(record.items, key=lambda value: value.created_at)
            ],
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

