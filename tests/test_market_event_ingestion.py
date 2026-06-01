from datetime import datetime, timezone

from stocks_tool.application.services.market_event_ingestion import (
    MarketEventIngestionService,
    load_market_event_csv,
)
from stocks_tool.domain.enums import MarketEventSeverity, MarketEventType
from stocks_tool.domain.models import CreateMarketEventRequest, MarketEvent


NOW = datetime(2026, 6, 1, 13, 30, tzinfo=timezone.utc)


class FakeMarketEvents:
    def __init__(self, existing: list[MarketEvent] | None = None) -> None:
        self.events = existing or []
        self.create_requests: list[CreateMarketEventRequest] = []

    def list_events(self, **kwargs) -> list[MarketEvent]:
        symbol = kwargs.get("symbol")
        event_type = kwargs.get("event_type")
        start = kwargs.get("start")
        end = kwargs.get("end")
        return [
            event
            for event in self.events
            if (symbol is None or event.symbol == symbol)
            and (event_type is None or event.event_type == event_type)
            and (start is None or event.scheduled_at >= start)
            and (end is None or event.scheduled_at <= end)
        ]

    def create_event(self, request: CreateMarketEventRequest) -> MarketEvent:
        self.create_requests.append(request)
        event = MarketEvent(
            id=f"event-{len(self.events) + 1}",
            symbol=request.symbol.upper() if request.symbol else None,
            event_type=request.event_type,
            title=request.title,
            scheduled_at=request.scheduled_at,
            source=request.source,
            severity=request.severity,
            notes=request.notes,
            raw_payload=request.raw_payload,
            created_at=NOW,
            updated_at=NOW,
        )
        self.events.append(event)
        return event


def test_market_event_ingestion_skips_duplicate_event() -> None:
    existing = MarketEvent(
        id="event-1",
        symbol="UNH.US",
        event_type=MarketEventType.EARNINGS,
        title="UNH Earnings",
        scheduled_at=NOW,
        source="manual",
        severity=MarketEventSeverity.HIGH,
        created_at=NOW,
        updated_at=NOW,
    )
    repository = FakeMarketEvents([existing])
    service = MarketEventIngestionService(repository)

    result = service.import_events(
        [
            CreateMarketEventRequest(
                symbol="UNH.US",
                event_type=MarketEventType.EARNINGS,
                title="  unh earnings  ",
                scheduled_at=NOW,
                source="manual",
                severity=MarketEventSeverity.HIGH,
            ),
            CreateMarketEventRequest(
                symbol=None,
                event_type=MarketEventType.FOMC,
                title="FOMC statement",
                scheduled_at=datetime(2026, 6, 17, 18, 0, tzinfo=timezone.utc),
                source="manual",
                severity=MarketEventSeverity.HIGH,
            ),
        ]
    )

    assert result.requested == 2
    assert result.created == 1
    assert result.skipped_duplicates == 1
    assert result.events[0].title == "FOMC statement"
    assert len(repository.create_requests) == 1


def test_load_market_event_csv_returns_create_requests(tmp_path) -> None:
    csv_path = tmp_path / "events.csv"
    csv_path.write_text(
        "symbol,event_type,title,scheduled_at,severity,source,notes,provider_id\n"
        "unh.us,earnings,UNH earnings,2026-06-01T13:30:00,High,manual,Watch risk,abc-1\n",
        encoding="utf-8",
    )

    requests = load_market_event_csv(csv_path)

    assert len(requests) == 1
    assert requests[0].symbol == "UNH.US"
    assert requests[0].scheduled_at == NOW
    assert requests[0].raw_payload == {"provider_id": "abc-1"}
