from __future__ import annotations

from datetime import date
from typing import Protocol

from stocks_tool.adapters.market_events.fmp import FmpMarketEventProvider
from stocks_tool.application.services.market_event_ingestion import MarketEventIngestionService
from stocks_tool.core.config import Settings
from stocks_tool.domain.models import (
    CreateMarketEventRequest,
    ImportMarketEventsFromProviderRequest,
    MarketEventImportResult,
)


class MarketEventProvider(Protocol):
    def fetch_events(
        self,
        *,
        start: date,
        end: date,
        symbols: list[str] | None = None,
    ) -> list[CreateMarketEventRequest]:
        ...


class SettingsMarketEventProviderFactory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create(self, provider: str) -> MarketEventProvider:
        normalized = provider.strip().casefold()
        if normalized == "fmp":
            return FmpMarketEventProvider(
                api_key=self.settings.fmp_api_key,
                base_url=self.settings.fmp_base_url,
                timeout_seconds=self.settings.market_event_provider_timeout_seconds,
            )
        raise ValueError(f"Unsupported market event provider: {provider}.")


class MarketEventProviderIngestionService:
    def __init__(
        self,
        *,
        ingestion_service: MarketEventIngestionService,
        provider_factory: SettingsMarketEventProviderFactory,
    ) -> None:
        self.ingestion_service = ingestion_service
        self.provider_factory = provider_factory

    def import_from_provider(
        self,
        request: ImportMarketEventsFromProviderRequest,
    ) -> MarketEventImportResult:
        if request.end < request.start:
            raise ValueError("Market event provider import end date must be on or after start date.")
        provider = self.provider_factory.create(request.provider)
        events = provider.fetch_events(
            start=request.start,
            end=request.end,
            symbols=[symbol.strip().upper() for symbol in request.symbols if symbol.strip()],
        )
        return self.ingestion_service.import_events(events)
