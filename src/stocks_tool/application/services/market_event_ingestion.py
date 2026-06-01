from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stocks_tool.domain.models import (
    CreateMarketEventRequest,
    MarketEvent,
    MarketEventImportResult,
)
from stocks_tool.ports.repository import MarketEventRepository


REQUIRED_MARKET_EVENT_COLUMNS = {"event_type", "title", "scheduled_at"}
OPTIONAL_MARKET_EVENT_COLUMNS = {"symbol", "source", "severity", "notes"}


class MarketEventIngestionService:
    def __init__(self, events: MarketEventRepository) -> None:
        self.events = events

    def import_csv(self, path: Path) -> MarketEventImportResult:
        return self.import_events(load_market_event_csv(path))

    def import_events(self, requests: list[CreateMarketEventRequest]) -> MarketEventImportResult:
        created_events: list[MarketEvent] = []
        skipped_duplicates = 0
        for request in requests:
            if self._event_exists(request):
                skipped_duplicates += 1
                continue
            created_events.append(self.events.create_event(request))
        return MarketEventImportResult(
            requested=len(requests),
            created=len(created_events),
            skipped_duplicates=skipped_duplicates,
            events=created_events,
        )

    def _event_exists(self, request: CreateMarketEventRequest) -> bool:
        scheduled_at = normalize_market_event_timestamp(request.scheduled_at)
        candidates = self.events.list_events(
            symbol=request.symbol,
            event_type=request.event_type,
            start=scheduled_at,
            end=scheduled_at,
            limit=500,
        )
        return any(self._same_event(candidate, request) for candidate in candidates)

    @staticmethod
    def _same_event(event: MarketEvent, request: CreateMarketEventRequest) -> bool:
        return (
            normalize_market_event_symbol(event.symbol) == normalize_market_event_symbol(request.symbol)
            and event.event_type == request.event_type
            and normalize_market_event_title(event.title) == normalize_market_event_title(request.title)
            and normalize_market_event_timestamp(event.scheduled_at)
            == normalize_market_event_timestamp(request.scheduled_at)
        )


def load_market_event_csv(path: Path) -> list[CreateMarketEventRequest]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file has no header row.")
        missing = REQUIRED_MARKET_EVENT_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"CSV file is missing required columns: {', '.join(sorted(missing))}.")
        return [
            CreateMarketEventRequest.model_validate(normalize_market_event_row(row))
            for row in reader
            if any((value or "").strip() for value in row.values())
        ]


def normalize_market_event_row(row: dict[str, str | None]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event_type": clean_market_event_value(row.get("event_type")).lower(),
        "title": clean_market_event_value(row.get("title")),
        "scheduled_at": normalize_market_event_timestamp_string(
            clean_market_event_value(row.get("scheduled_at"))
        ),
    }
    for field in OPTIONAL_MARKET_EVENT_COLUMNS:
        value = clean_market_event_value(row.get(field))
        if not value:
            continue
        if field == "symbol":
            payload[field] = value.upper()
        elif field == "severity":
            payload[field] = value.lower()
        else:
            payload[field] = value
    raw_payload = {
        key: value
        for key, value in row.items()
        if key not in REQUIRED_MARKET_EVENT_COLUMNS
        and key not in OPTIONAL_MARKET_EVENT_COLUMNS
        and value not in {None, ""}
    }
    if raw_payload:
        payload["raw_payload"] = raw_payload
    return payload


def normalize_market_event_timestamp_string(value: str) -> str:
    if not value:
        raise ValueError("scheduled_at is required.")
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return normalize_market_event_timestamp(parsed).isoformat().replace("+00:00", "Z")


def normalize_market_event_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_market_event_symbol(value: str | None) -> str | None:
    return value.strip().upper() if value else None


def normalize_market_event_title(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def clean_market_event_value(value: str | None) -> str:
    return (value or "").strip()
