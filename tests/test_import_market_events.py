from pathlib import Path

from scripts.import_market_events import load_rows, normalize_timestamp


def test_normalize_timestamp_assumes_utc_for_naive_values() -> None:
    assert normalize_timestamp("2026-06-01T13:30:00") == "2026-06-01T13:30:00Z"


def test_load_rows_normalizes_market_event_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "events.csv"
    csv_path.write_text(
        "symbol,event_type,title,scheduled_at,severity,source,notes,provider_id\n"
        "unh.us,earnings,UNH earnings,2026-06-01T13:30:00Z,High,manual,Watch premium risk,abc-1\n",
        encoding="utf-8",
    )

    rows = load_rows(csv_path)

    assert rows == [
        {
            "event_type": "earnings",
            "title": "UNH earnings",
            "scheduled_at": "2026-06-01T13:30:00Z",
            "symbol": "UNH.US",
            "source": "manual",
            "severity": "high",
            "notes": "Watch premium risk",
            "raw_payload": {"provider_id": "abc-1"},
        }
    ]
