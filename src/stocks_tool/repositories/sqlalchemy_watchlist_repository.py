from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from stocks_tool.db.models import WatchlistItemRecord, WatchlistRecord
from stocks_tool.domain.enums import AssetType
from stocks_tool.domain.models import (
    AddWatchlistItemRequest,
    CreateWatchlistRequest,
    UpdateWatchlistItemRequest,
    UpdateWatchlistRequest,
    Watchlist,
    WatchlistItem,
)
from stocks_tool.ports.repository import WatchlistItemConflictError, WatchlistRepository


class SQLAlchemyWatchlistRepository(WatchlistRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_watchlist(self, request: CreateWatchlistRequest) -> Watchlist:
        if request.is_default:
            for existing in self.session.execute(select(WatchlistRecord)).scalars():
                existing.is_default = False
        record = WatchlistRecord(
            name=request.name.strip(),
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

    def get_watchlist(self, watchlist_id: str) -> Watchlist | None:
        record = self._load_watchlist_record(watchlist_id)
        return self._to_domain(record) if record is not None else None

    def add_item(self, watchlist_id: str, request: AddWatchlistItemRequest) -> Watchlist | None:
        record = self.session.get(WatchlistRecord, watchlist_id)
        if record is None:
            return None

        normalized_symbol = request.symbol.strip().upper()
        existing = self.session.execute(
            select(WatchlistItemRecord.id)
            .where(
                WatchlistItemRecord.watchlist_id == watchlist_id,
                func.upper(func.trim(WatchlistItemRecord.symbol)) == normalized_symbol,
            )
            .limit(1)
        ).scalar()
        if existing is not None:
            raise WatchlistItemConflictError(normalized_symbol)

        item = WatchlistItemRecord(
            watchlist_id=watchlist_id,
            symbol=normalized_symbol,
            asset_type=request.asset_type.value,
            notes=request.notes,
        )
        self.session.add(item)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            if self._is_symbol_conflict(exc):
                raise WatchlistItemConflictError(normalized_symbol) from exc
            raise

        return self.get_watchlist(watchlist_id)

    @staticmethod
    def _is_symbol_conflict(error: IntegrityError) -> bool:
        detail = str(error.orig).lower()
        return (
            "uq_watchlist_items_watchlist_symbol" in detail
            or "watchlist_items.watchlist_id, watchlist_items.symbol" in detail
        )

    def update_watchlist(
        self,
        watchlist_id: str,
        request: UpdateWatchlistRequest,
    ) -> Watchlist | None:
        record = self.session.get(WatchlistRecord, watchlist_id)
        if record is None:
            return None
        if "name" in request.model_fields_set:
            record.name = request.name.strip() if request.name is not None else record.name
        if "description" in request.model_fields_set:
            record.description = request.description
        if "is_default" in request.model_fields_set:
            record.is_default = bool(request.is_default)
            if request.is_default:
                for other in self.session.execute(
                    select(WatchlistRecord).where(WatchlistRecord.id != watchlist_id)
                ).scalars():
                    other.is_default = False
        self.session.commit()
        return self.get_watchlist(watchlist_id)

    def update_item(
        self,
        watchlist_id: str,
        item_id: str,
        request: UpdateWatchlistItemRequest,
    ) -> Watchlist | None:
        item = self.session.execute(
            select(WatchlistItemRecord).where(
                WatchlistItemRecord.id == item_id,
                WatchlistItemRecord.watchlist_id == watchlist_id,
            )
        ).scalar_one_or_none()
        if item is None:
            return None
        item.notes = request.notes
        self.session.commit()
        return self.get_watchlist(watchlist_id)

    def delete_item(self, watchlist_id: str, item_id: str) -> bool:
        item = self.session.execute(
            select(WatchlistItemRecord).where(
                WatchlistItemRecord.id == item_id,
                WatchlistItemRecord.watchlist_id == watchlist_id,
            )
        ).scalar_one_or_none()
        if item is None:
            return False
        self.session.delete(item)
        self.session.commit()
        return True

    def _load_watchlist_record(self, watchlist_id: str) -> WatchlistRecord | None:
        return self.session.execute(
            select(WatchlistRecord)
            .options(selectinload(WatchlistRecord.items))
            .where(WatchlistRecord.id == watchlist_id)
        ).scalars().unique().one_or_none()

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
