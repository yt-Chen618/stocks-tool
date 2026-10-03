import hashlib
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stocks_tool.db.models import MarketEventRecord
from stocks_tool.domain.enums import MarketEventSeverity, MarketEventType
from stocks_tool.domain.models import CreateMarketEventRequest, MarketEvent
from stocks_tool.domain.pagination import CursorPage
from stocks_tool.ports.repository import MarketEventRepository


class SQLAlchemyMarketEventRepository(MarketEventRepository):
    LEGACY_DEDUPE_PAGE_SIZE = 500

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_event(self, request: CreateMarketEventRequest) -> MarketEvent:
        event, _created = self.create_event_if_absent(request)
        return event

    def create_event_if_absent(
        self,
        request: CreateMarketEventRequest,
    ) -> tuple[MarketEvent, bool]:
        identity = self._normalized_identity(request)
        legacy = self._find_legacy_identity(identity)
        if legacy is not None:
            return self._to_domain(legacy), False
        dedupe_key = self._dedupe_key(request)
        record = MarketEventRecord(
            symbol=identity[0] or None,
            event_type=request.event_type.value,
            title=request.title.strip(),
            scheduled_at=identity[3],
            dedupe_key=dedupe_key,
            source=request.source.strip() if request.source else None,
            severity=request.severity.value,
            notes=request.notes,
            raw_payload=request.raw_payload,
        )
        self.session.add(record)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.execute(
                select(MarketEventRecord).where(
                    MarketEventRecord.dedupe_key == dedupe_key,
                )
            ).scalar_one_or_none()
            if existing is not None:
                return self._to_domain(existing), False
            legacy = self._find_legacy_identity(identity)
            if legacy is not None:
                return self._to_domain(legacy), False
            raise
        self.session.refresh(record)
        return self._to_domain(record), True

    @staticmethod
    def _dedupe_key(request: CreateMarketEventRequest) -> str:
        symbol, event_type, title, scheduled_at = (
            SQLAlchemyMarketEventRepository._normalized_identity(request)
        )
        canonical = "\x1f".join(
            (
                symbol,
                event_type,
                title,
                scheduled_at.isoformat(),
            )
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalized_identity(
        request: CreateMarketEventRequest,
    ) -> tuple[str, str, str, datetime]:
        symbol = request.symbol.strip().upper() if request.symbol else ""
        event_type = request.event_type.value
        title = " ".join(request.title.strip().casefold().split())
        scheduled_at = request.scheduled_at
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        else:
            scheduled_at = scheduled_at.astimezone(timezone.utc)
        return symbol, event_type, title, scheduled_at

    def _find_legacy_identity(
        self,
        identity: tuple[str, str, str, datetime],
    ) -> MarketEventRecord | None:
        symbol, event_type, title, scheduled_at = identity
        cursor: tuple[datetime, str] | None = None
        while True:
            query = select(MarketEventRecord).where(
                MarketEventRecord.dedupe_key.is_(None),
                MarketEventRecord.event_type == event_type,
                MarketEventRecord.scheduled_at == scheduled_at,
            )
            if cursor is not None:
                cursor_created_at, cursor_id = cursor
                query = query.where(
                    or_(
                        MarketEventRecord.created_at > cursor_created_at,
                        and_(
                            MarketEventRecord.created_at == cursor_created_at,
                            MarketEventRecord.id > cursor_id,
                        ),
                    )
                )
            candidates = self.session.execute(
                query.order_by(
                    MarketEventRecord.created_at.asc(),
                    MarketEventRecord.id.asc(),
                ).limit(self.LEGACY_DEDUPE_PAGE_SIZE)
            ).scalars().all()
            if not candidates:
                return None
            for candidate in candidates:
                candidate_identity = (
                    candidate.symbol.strip().upper() if candidate.symbol else "",
                    candidate.event_type,
                    " ".join(candidate.title.strip().casefold().split()),
                    self._normalize_timestamp(candidate.scheduled_at),
                )
                if candidate_identity == (symbol, event_type, title, scheduled_at):
                    return candidate
            last = candidates[-1]
            cursor = (last.created_at, last.id)

    @staticmethod
    def _normalize_timestamp(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def list_events(
        self,
        *,
        symbol: str | None = None,
        symbols: list[str] | None = None,
        event_type: MarketEventType | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = 100,
    ) -> list[MarketEvent]:
        query = select(MarketEventRecord).order_by(MarketEventRecord.scheduled_at.asc())
        if symbol is not None:
            query = query.where(MarketEventRecord.symbol == symbol.strip().upper())
        if symbols is not None:
            normalized_symbols = {value.strip().upper() for value in symbols if value.strip()}
            symbol_filters = [MarketEventRecord.symbol.is_(None)]
            if normalized_symbols:
                symbol_filters.append(MarketEventRecord.symbol.in_(normalized_symbols))
            query = query.where(or_(*symbol_filters))
        if event_type is not None:
            query = query.where(MarketEventRecord.event_type == event_type.value)
        if start is not None:
            query = query.where(MarketEventRecord.scheduled_at >= start)
        if end is not None:
            query = query.where(MarketEventRecord.scheduled_at <= end)
        if limit is not None:
            query = query.limit(limit)
        return [self._to_domain(record) for record in self.session.execute(query).scalars().all()]

    def list_events_page(
        self,
        *,
        symbols: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        cursor_scheduled_at: datetime | None = None,
        cursor_id: str | None = None,
        limit: int = 50,
    ) -> CursorPage[MarketEvent]:
        """Return a bounded ascending keyset page for research timelines."""

        normalized_symbols = {value.strip().upper() for value in (symbols or []) if value.strip()}
        query = select(MarketEventRecord)
        if symbols is not None:
            symbol_filters = [MarketEventRecord.symbol.is_(None)]
            if normalized_symbols:
                symbol_filters.append(MarketEventRecord.symbol.in_(normalized_symbols))
            query = query.where(or_(*symbol_filters))
        if start is not None:
            query = query.where(MarketEventRecord.scheduled_at >= start)
        if end is not None:
            query = query.where(MarketEventRecord.scheduled_at <= end)
        if cursor_scheduled_at is not None:
            cursor_filter = MarketEventRecord.scheduled_at > cursor_scheduled_at
            if cursor_id is not None:
                cursor_filter = or_(
                    cursor_filter,
                    and_(
                        MarketEventRecord.scheduled_at == cursor_scheduled_at,
                        MarketEventRecord.id > cursor_id,
                    ),
                )
            query = query.where(cursor_filter)
        query = query.order_by(
            MarketEventRecord.scheduled_at.asc(),
            MarketEventRecord.id.asc(),
        ).limit(limit)
        records = self.session.execute(query).scalars().all()
        # The caller requests limit+1 and uses this flag to build the global
        # timeline cursor.  Keep the method's return envelope typed while
        # preserving the exact bounded rows from the database.
        return CursorPage(
            items=[self._to_domain(record) for record in records],
            next_cursor=None,
            has_more=len(records) >= limit,
            limit=min(max(limit, 1), 100),
        )

    @staticmethod
    def _to_domain(record: MarketEventRecord) -> MarketEvent:
        return MarketEvent(
            id=record.id,
            symbol=record.symbol,
            event_type=MarketEventType(record.event_type),
            title=record.title,
            scheduled_at=record.scheduled_at,
            source=record.source,
            severity=MarketEventSeverity(record.severity),
            notes=record.notes,
            raw_payload=record.raw_payload,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
