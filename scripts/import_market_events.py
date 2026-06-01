from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx

from stocks_tool.application.services.market_event_ingestion import (
    load_market_event_csv,
    normalize_market_event_row,
    normalize_market_event_timestamp_string,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import market events from CSV into the local API.")
    parser.add_argument("--csv", required=True, help="CSV path with event_type,title,scheduled_at columns.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Local API base URL.")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds.")
    return parser.parse_args()


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


def main() -> None:
    args = parse_args()
    rows = load_rows(Path(args.csv))
    result = import_events(base_url=args.base_url, rows=rows, timeout=args.timeout)
    print(
        json.dumps(
            {
                "script": "import_market_events.py",
                "status": "passed",
                "requested": len(rows),
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
