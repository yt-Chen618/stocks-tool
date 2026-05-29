from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocks_tool.db.models import MarketEventRecord
from stocks_tool.domain.enums import MarketEventSeverity, MarketEventType
from stocks_tool.domain.models import CreateMarketEventRequest, MarketEvent
from stocks_tool.ports.repository import MarketEventRepository


class SQLAlchemyMarketEventRepository(MarketEventRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_event(self, request: CreateMarketEventRequest) -> MarketEvent:
        record = MarketEventRecord(
            symbol=request.symbol.strip().upper() if request.symbol else None,
            event_type=request.event_type.value,
            title=request.title.strip(),
            scheduled_at=request.scheduled_at,
            source=request.source.strip() if request.source else None,
            severity=request.severity.value,
            notes=request.notes,
            raw_payload=request.raw_payload,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def list_events(
        self,
        *,
        symbol: str | None = None,
        event_type: MarketEventType | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[MarketEvent]:
        query = select(MarketEventRecord).order_by(MarketEventRecord.scheduled_at.asc()).limit(limit)
        if symbol is not None:
            query = query.where(MarketEventRecord.symbol == symbol.strip().upper())
        if event_type is not None:
            query = query.where(MarketEventRecord.event_type == event_type.value)
        if start is not None:
            query = query.where(MarketEventRecord.scheduled_at >= start)
        if end is not None:
            query = query.where(MarketEventRecord.scheduled_at <= end)
        return [self._to_domain(record) for record in self.session.execute(query).scalars().all()]

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
