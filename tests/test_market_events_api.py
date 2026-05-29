from datetime import datetime, timezone

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_market_event_repository
from stocks_tool.domain.enums import MarketEventSeverity, MarketEventType
from stocks_tool.domain.models import CreateMarketEventRequest, MarketEvent
from stocks_tool.main import app


NOW = datetime(2026, 6, 1, 13, 30, tzinfo=timezone.utc)


class FakeMarketEventRepository:
    def __init__(self) -> None:
        self.events: list[MarketEvent] = [
            MarketEvent(
                id="event-1",
                symbol="UNH.US",
                event_type=MarketEventType.EARNINGS,
                title="UNH earnings",
                scheduled_at=NOW,
                source="manual",
                severity=MarketEventSeverity.HIGH,
                created_at=NOW,
                updated_at=NOW,
            )
        ]
        self.list_request = None
        self.create_request = None

    def list_events(self, **kwargs) -> list[MarketEvent]:
        self.list_request = kwargs
        return self.events

    def create_event(self, request: CreateMarketEventRequest) -> MarketEvent:
        self.create_request = request
        event = MarketEvent(
            id="event-2",
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


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_list_market_events_route_returns_filtered_events() -> None:
    repository = FakeMarketEventRepository()
    app.dependency_overrides[get_market_event_repository] = lambda: repository
    client = TestClient(app)
    try:
        response = client.get(
            "/market-events",
            params={"symbol": "UNH.US", "event_type": "earnings", "limit": "25"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == "event-1"
    assert repository.list_request["symbol"] == "UNH.US"
    assert repository.list_request["event_type"] == MarketEventType.EARNINGS
    assert repository.list_request["limit"] == 25


def test_create_market_event_route_persists_event() -> None:
    repository = FakeMarketEventRepository()
    app.dependency_overrides[get_market_event_repository] = lambda: repository
    client = TestClient(app)
    try:
        response = client.post(
            "/market-events",
            json={
                "symbol": "UNH.US",
                "event_type": "earnings",
                "title": "UNH earnings",
                "scheduled_at": "2026-06-01T13:30:00Z",
                "source": "manual",
                "severity": "high",
                "notes": "Avoid opening new short-vol premium trades into the event.",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "event-2"
    assert body["severity"] == "high"
    assert repository.create_request.symbol == "UNH.US"
