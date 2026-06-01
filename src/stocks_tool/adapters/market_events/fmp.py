from __future__ import annotations

import logging
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import httpx

from stocks_tool.domain.enums import MarketEventSeverity, MarketEventType
from stocks_tool.domain.models import CreateMarketEventRequest


logger = logging.getLogger(__name__)


class FmpMarketEventProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://financialmodelingprep.com",
        timeout_seconds: int = 20,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("FMP market event import requires FMP_API_KEY.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.new_york = ZoneInfo("America/New_York")

    def fetch_events(
        self,
        *,
        start: date,
        end: date,
        symbols: list[str] | None = None,
    ) -> list[CreateMarketEventRequest]:
        if end < start:
            raise ValueError("Market event provider import end date must be on or after start date.")
        symbol_filter = {provider_symbol_for_local_symbol(symbol) for symbol in symbols or []}
        with httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            earnings = self._get_json(
                client,
                "/stable/earnings-calendar",
                {"from": start.isoformat(), "to": end.isoformat()},
            )
            economic = self._get_optional_json(
                client,
                "/stable/economic-calendar",
                {"from": start.isoformat(), "to": end.isoformat()},
                endpoint_name="economic calendar",
            )

        requests: list[CreateMarketEventRequest] = []
        for row in earnings:
            event = self._map_earnings_event(row, symbol_filter=symbol_filter)
            if event is not None:
                requests.append(event)
        for row in economic:
            event = self._map_economic_event(row)
            if event is not None:
                requests.append(event)
        return requests

    def _get_json(
        self,
        client: httpx.Client,
        path: str,
        params: dict[str, str],
    ) -> list[dict]:
        response = client.get(path, params={**params, "apikey": self.api_key})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError(f"FMP endpoint {path} returned a non-list payload.")
        return [row for row in data if isinstance(row, dict)]

    def _get_optional_json(
        self,
        client: httpx.Client,
        path: str,
        params: dict[str, str],
        *,
        endpoint_name: str,
    ) -> list[dict]:
        try:
            return self._get_json(client, path, params)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            logger.warning("Skipping optional FMP %s endpoint after HTTP %s.", endpoint_name, status_code)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "Skipping optional FMP %s endpoint after provider error: %s.",
                endpoint_name,
                exc.__class__.__name__,
            )
        return []

    def _map_earnings_event(
        self,
        row: dict,
        *,
        symbol_filter: set[str],
    ) -> CreateMarketEventRequest | None:
        provider_symbol = clean_string(row.get("symbol")).upper()
        if not provider_symbol:
            return None
        if symbol_filter and provider_symbol not in symbol_filter:
            return None
        event_date = parse_provider_date(row.get("date"))
        if event_date is None:
            return None
        scheduled_at = self._scheduled_at(event_date, market_time=row.get("time"))
        notes = compact_notes(
            [
                formatted_field("time", row.get("time")),
                formatted_field("eps_estimated", row.get("epsEstimated")),
                formatted_field("revenue_estimated", row.get("revenueEstimated")),
            ]
        )
        return CreateMarketEventRequest(
            symbol=local_symbol_for_provider_symbol(provider_symbol),
            event_type=MarketEventType.EARNINGS,
            title=f"{provider_symbol} earnings",
            scheduled_at=scheduled_at,
            source="fmp",
            severity=MarketEventSeverity.HIGH,
            notes=notes,
            raw_payload=provider_payload("fmp_earnings_calendar", row),
        )

    def _map_economic_event(self, row: dict) -> CreateMarketEventRequest | None:
        country = clean_string(row.get("country")).upper()
        if country and country not in {"US", "USA", "UNITED STATES"}:
            return None
        title = clean_string(row.get("event") or row.get("title") or row.get("name"))
        if not title:
            return None
        event_type = classify_macro_event(title)
        if event_type is None:
            return None
        scheduled_at = parse_provider_datetime(row.get("date"), self.new_york)
        if scheduled_at is None:
            return None
        notes = compact_notes(
            [
                formatted_field("country", row.get("country")),
                formatted_field("actual", row.get("actual")),
                formatted_field("estimate", row.get("estimate")),
                formatted_field("previous", row.get("previous")),
            ]
        )
        return CreateMarketEventRequest(
            event_type=event_type,
            title=title,
            scheduled_at=scheduled_at,
            source="fmp",
            severity=macro_severity(row.get("impact"), event_type),
            notes=notes,
            raw_payload=provider_payload("fmp_economic_calendar", row),
        )

    def _scheduled_at(self, event_date: date, *, market_time: object) -> datetime:
        normalized = clean_string(market_time).casefold()
        if normalized in {"bmo", "before market open", "before_open"}:
            local_time = time(8, 0)
        elif normalized in {"amc", "after market close", "after_close"}:
            local_time = time(16, 5)
        elif normalized in {"dmh", "during market hours", "during_market"}:
            local_time = time(12, 0)
        else:
            local_time = time(12, 0)
        return datetime.combine(event_date, local_time, tzinfo=self.new_york).astimezone(ZoneInfo("UTC"))


def classify_macro_event(title: str) -> MarketEventType | None:
    normalized = title.casefold()
    if "fomc" in normalized or "interest rate" in normalized or "federal open market" in normalized:
        return MarketEventType.FOMC
    if "cpi" in normalized or "consumer price index" in normalized:
        return MarketEventType.CPI
    if (
        "nonfarm payroll" in normalized
        or "unemployment" in normalized
        or "jobless" in normalized
        or "employment" in normalized
    ):
        return MarketEventType.JOBS
    return None


def macro_severity(value: object, event_type: MarketEventType) -> MarketEventSeverity:
    normalized = clean_string(value).casefold()
    if "high" in normalized:
        return MarketEventSeverity.HIGH
    if "low" in normalized:
        return MarketEventSeverity.LOW
    if event_type in {MarketEventType.CPI, MarketEventType.FOMC, MarketEventType.JOBS}:
        return MarketEventSeverity.HIGH
    return MarketEventSeverity.MEDIUM


def provider_symbol_for_local_symbol(value: str) -> str:
    symbol = clean_string(value).upper()
    return symbol.removesuffix(".US")


def local_symbol_for_provider_symbol(value: str) -> str:
    symbol = clean_string(value).upper()
    if "." in symbol:
        return symbol
    return f"{symbol}.US"


def parse_provider_date(value: object) -> date | None:
    text = clean_string(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_provider_datetime(value: object, fallback_timezone: ZoneInfo) -> datetime | None:
    text = clean_string(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        event_date = parse_provider_date(text)
        if event_date is None:
            return None
        parsed = datetime.combine(event_date, time(12, 0), tzinfo=fallback_timezone)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=fallback_timezone)
    return parsed.astimezone(ZoneInfo("UTC"))


def provider_payload(endpoint: str, row: dict) -> dict:
    return {
        "provider": "fmp",
        "endpoint": endpoint,
        "payload": dict(row),
    }


def compact_notes(parts: list[str | None]) -> str | None:
    values = [part for part in parts if part]
    return "; ".join(values) if values else None


def formatted_field(label: str, value: object) -> str | None:
    text = clean_string(value)
    return f"{label}={text}" if text else None


def clean_string(value: object) -> str:
    return str(value or "").strip()
