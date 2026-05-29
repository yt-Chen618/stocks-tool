from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


REQUIRED_COLUMNS = {"event_type", "title", "scheduled_at"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import market events from CSV into the local API.")
    parser.add_argument("--csv", required=True, help="CSV path with event_type,title,scheduled_at columns.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Local API base URL.")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds.")
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file has no header row.")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"CSV file is missing required columns: {', '.join(sorted(missing))}.")
        return [normalize_row(row) for row in reader if any((value or "").strip() for value in row.values())]


def normalize_row(row: dict[str, str | None]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event_type": clean(row.get("event_type")).lower(),
        "title": clean(row.get("title")),
        "scheduled_at": normalize_timestamp(clean(row.get("scheduled_at"))),
    }
    optional_fields = ("symbol", "source", "severity", "notes")
    for field in optional_fields:
        value = clean(row.get(field))
        if value:
            payload[field] = value.upper() if field == "symbol" else value.lower() if field == "severity" else value
    raw_payload = {
        key: value
        for key, value in row.items()
        if key not in {*REQUIRED_COLUMNS, *optional_fields} and value not in {None, ""}
    }
    if raw_payload:
        payload["raw_payload"] = raw_payload
    return payload


def normalize_timestamp(value: str) -> str:
    if not value:
        raise ValueError("scheduled_at is required.")
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def clean(value: str | None) -> str:
    return (value or "").strip()


def import_events(*, base_url: str, rows: list[dict[str, Any]], timeout: float) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        for row in rows:
            response = client.post("/market-events", json=row)
            response.raise_for_status()
            created.append(response.json())
    return created


def main() -> None:
    args = parse_args()
    rows = load_rows(Path(args.csv))
    created = import_events(base_url=args.base_url, rows=rows, timeout=args.timeout)
    print(
        json.dumps(
            {
                "script": "import_market_events.py",
                "status": "passed",
                "requested": len(rows),
                "created": len(created),
                "events": created,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
