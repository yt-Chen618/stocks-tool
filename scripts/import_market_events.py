from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stocks_tool.application.services.market_event_ingestion import (
    load_market_event_csv,
    normalize_market_event_row,
    normalize_market_event_timestamp_string,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import market events into the local API.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", help="CSV path with event_type,title,scheduled_at columns.")
    source.add_argument("--provider", help="Provider name for API-backed event import, for example fmp.")
    parser.add_argument("--start", help="Provider import start date in YYYY-MM-DD format.")
    parser.add_argument("--end", help="Provider import end date in YYYY-MM-DD format.")
    parser.add_argument("--symbols", default="", help="Comma-separated local symbols for provider earnings filters.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Local API base URL.")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds.")
    args = parser.parse_args()
    if args.provider and (not args.start or not args.end):
        parser.error("--provider requires --start and --end.")
    return args


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [request.model_dump(mode="json") for request in load_market_event_csv(path)]


def normalize_row(row: dict[str, str | None]) -> dict[str, Any]:
    return normalize_market_event_row(row)


def normalize_timestamp(value: str) -> str:
    return normalize_market_event_timestamp_string(value)


def import_events(*, base_url: str, rows: list[dict[str, Any]], timeout: float) -> dict[str, Any]:
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        response = client.post("/market-events/import", json={"events": rows})
        response.raise_for_status()
        return response.json()


def import_provider_events(
    *,
    base_url: str,
    provider: str,
    start: str,
    end: str,
    symbols: str,
    timeout: float,
) -> dict[str, Any]:
    payload = {
        "provider": provider,
        "start": date.fromisoformat(start).isoformat(),
        "end": date.fromisoformat(end).isoformat(),
        "symbols": [symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip()],
    }
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        response = client.post("/market-events/import/provider", json=payload)
        response.raise_for_status()
        return response.json()


def main() -> None:
    args = parse_args()
    if args.csv:
        rows = load_rows(Path(args.csv))
        requested = len(rows)
        result = import_events(base_url=args.base_url, rows=rows, timeout=args.timeout)
        source = "csv"
    else:
        result = import_provider_events(
            base_url=args.base_url,
            provider=args.provider,
            start=args.start,
            end=args.end,
            symbols=args.symbols,
            timeout=args.timeout,
        )
        requested = result["requested"]
        source = args.provider
    print(
        json.dumps(
            {
                "script": "import_market_events.py",
                "status": "passed",
                "source": source,
                "requested": requested,
                "created": result["created"],
                "skipped_duplicates": result["skipped_duplicates"],
                "events": result["events"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
