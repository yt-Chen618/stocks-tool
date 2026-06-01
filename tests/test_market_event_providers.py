from datetime import date, datetime, timezone

import httpx

from stocks_tool.adapters.market_events.fmp import FmpMarketEventProvider
from stocks_tool.application.services.market_event_ingestion import MarketEventIngestionService
from stocks_tool.application.services.market_event_provider_ingestion import (
    MarketEventProviderIngestionService,
)
from stocks_tool.domain.enums import MarketEventSeverity, MarketEventType
from stocks_tool.domain.models import (
    CreateMarketEventRequest,
    ImportMarketEventsFromProviderRequest,
    MarketEvent,
)


class FakeMarketEvents:
    def __init__(self, existing: list[MarketEvent] | None = None) -> None:
        self.events = existing or []

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
        event = MarketEvent(
            id=f"event-{len(self.events) + 1}",
            symbol=request.symbol,
            event_type=request.event_type,
            title=request.title,
            scheduled_at=request.scheduled_at,
            source=request.source,
            severity=request.severity,
            notes=request.notes,
            raw_payload=request.raw_payload,
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        self.events.append(event)
        return event


def test_fmp_market_event_provider_maps_earnings_and_macro_events() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["apikey"] == "test-key"
        if request.url.path == "/stable/earnings-calendar":
            return httpx.Response(
                200,
                json=[
                    {
                        "symbol": "UNH",
                        "date": "2026-06-03",
                        "time": "bmo",
                        "epsEstimated": "5.10",
                        "revenueEstimated": "100000000000",
                    },
                    {"symbol": "MSFT", "date": "2026-06-03", "time": "amc"},
                ],
            )
        if request.url.path == "/stable/economic-calendar":
            return httpx.Response(
                200,
                json=[
                    {
                        "country": "US",
                        "event": "CPI Inflation Rate YoY",
                        "date": "2026-06-10 08:30:00",
                        "impact": "High",
                        "estimate": "2.6%",
                        "previous": "2.5%",
                    },
                    {"country": "CA", "event": "CPI", "date": "2026-06-10 08:30:00"},
                    {"country": "US", "event": "Retail Sales", "date": "2026-06-10 08:30:00"},
                ],
            )
        return httpx.Response(404)

    provider = FmpMarketEventProvider(
        api_key="test-key",
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )

    events = provider.fetch_events(
        start=date(2026, 6, 1),
        end=date(2026, 6, 15),
        symbols=["UNH.US"],
    )

    assert len(events) == 2
    earnings, cpi = events
    assert earnings.symbol == "UNH.US"
    assert earnings.event_type == MarketEventType.EARNINGS
    assert earnings.source == "fmp"
    assert earnings.severity == MarketEventSeverity.HIGH
    assert earnings.scheduled_at == datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    assert earnings.raw_payload["endpoint"] == "fmp_earnings_calendar"
    assert cpi.symbol is None
    assert cpi.event_type == MarketEventType.CPI
    assert cpi.scheduled_at == datetime(2026, 6, 10, 12, 30, tzinfo=timezone.utc)
    assert cpi.raw_payload["endpoint"] == "fmp_economic_calendar"


def test_fmp_market_event_provider_keeps_earnings_when_optional_macro_endpoint_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["apikey"] == "test-key"
        if request.url.path == "/stable/earnings-calendar":
            return httpx.Response(
                200,
                json=[{"symbol": "UNH", "date": "2026-06-03", "time": "bmo"}],
            )
        if request.url.path == "/stable/economic-calendar":
            return httpx.Response(402, json={"message": "payment required"})
        return httpx.Response(404)

    provider = FmpMarketEventProvider(
        api_key="test-key",
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )

    events = provider.fetch_events(
        start=date(2026, 6, 1),
        end=date(2026, 6, 15),
        symbols=["UNH.US"],
    )

    assert len(events) == 1
    assert events[0].symbol == "UNH.US"
    assert events[0].event_type == MarketEventType.EARNINGS


def test_market_event_provider_ingestion_uses_existing_duplicate_handling() -> None:
    existing = MarketEvent(
        id="event-1",
        symbol="UNH.US",
        event_type=MarketEventType.EARNINGS,
        title="UNH earnings",
        scheduled_at=datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc),
        source="fmp",
        severity=MarketEventSeverity.HIGH,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    class FakeProvider:
        def fetch_events(self, **kwargs) -> list[CreateMarketEventRequest]:
            return [
                CreateMarketEventRequest(
                    symbol="UNH.US",
                    event_type=MarketEventType.EARNINGS,
                    title="unh earnings",
                    scheduled_at=datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc),
                    source="fmp",
                    severity=MarketEventSeverity.HIGH,
                ),
                CreateMarketEventRequest(
                    event_type=MarketEventType.FOMC,
                    title="FOMC statement",
                    scheduled_at=datetime(2026, 6, 17, 18, 0, tzinfo=timezone.utc),
                    source="fmp",
                    severity=MarketEventSeverity.HIGH,
                ),
            ]

    class FakeProviderFactory:
        def create(self, provider: str) -> FakeProvider:
            assert provider == "fmp"
            return FakeProvider()

    repository = FakeMarketEvents([existing])
    service = MarketEventProviderIngestionService(
        ingestion_service=MarketEventIngestionService(repository),
        provider_factory=FakeProviderFactory(),
    )

    result = service.import_from_provider(
        ImportMarketEventsFromProviderRequest(
            provider="fmp",
            start=date(2026, 6, 1),
            end=date(2026, 6, 30),
            symbols=["UNH.US"],
        )
    )

    assert result.requested == 2
    assert result.created == 1
    assert result.skipped_duplicates == 1
    assert result.events[0].event_type == MarketEventType.FOMC
