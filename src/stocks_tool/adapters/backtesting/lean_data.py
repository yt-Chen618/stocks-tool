"""Canonical local data contract consumed by the offline LEAN algorithm.

The application does not pass arbitrary CSV files to LEAN.  Each registered
file must satisfy a category schema, expose point-in-time availability, and be
listed in a generated canonical manifest.  The manifest points at files that
are already inside the allowlisted data root; it never downloads or extracts
archives.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable
from zoneinfo import ZoneInfo

from stocks_tool.domain.backtesting import DataFile, DatasetCategory, canonical_json

if TYPE_CHECKING:
    from stocks_tool.adapters.backtesting.lean_staging import LeanStagingResult


_ALIASES: dict[str, tuple[str, ...]] = {
    "symbol": ("symbol", "ticker", "contract_symbol"),
    "underlying": ("underlying", "underlying_symbol", "root"),
    "date": ("date", "trading_date", "event_date", "timestamp", "datetime", "time"),
    "available_at": ("available_at", "as_of", "published_at", "received_at"),
    "open": ("open",),
    "high": ("high",),
    "low": ("low",),
    "close": ("close",),
    "volume": ("volume", "size"),
    "bid": ("bid", "bid_price"),
    "ask": ("ask", "ask_price"),
    "price": ("price", "last", "trade_price"),
    "expiration": ("expiration", "expiration_date", "expiry"),
    "strike": ("strike", "strike_price"),
    "right": ("right", "option_right", "put_call"),
    "open_interest": ("open_interest", "oi"),
    "security_type": ("security_type", "asset_type", "type"),
    "effective_start": ("effective_start", "start_date", "date"),
    "effective_end": ("effective_end", "end_date"),
    "session_open": ("session_open", "open_time", "market_open"),
    "session_close": ("session_close", "close_time", "market_close"),
    "action": ("action", "event_type", "corporate_action"),
}

_REQUIRED: dict[DatasetCategory, tuple[str, ...]] = {
    DatasetCategory.SECURITY_MASTER: ("symbol", "security_type", "effective_start", "available_at"),
    DatasetCategory.UNDERLYING_BARS: (
        "symbol",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "available_at",
    ),
    DatasetCategory.OPTION_QUOTES: (
        "symbol",
        "underlying",
        "expiration",
        "strike",
        "right",
        "date",
        "bid",
        "ask",
        "available_at",
    ),
    DatasetCategory.OPTION_TRADES: (
        "symbol",
        "underlying",
        "expiration",
        "strike",
        "right",
        "date",
        "price",
        "volume",
        "available_at",
    ),
    DatasetCategory.OPEN_INTEREST: ("symbol", "date", "open_interest", "available_at"),
    DatasetCategory.CALENDARS: ("date", "session_open", "session_close"),
    DatasetCategory.CORPORATE_ACTIONS: ("symbol", "date", "action", "available_at"),
}
TRUSTED_US_EXCHANGE_CALENDAR_SOURCES = (
    "https://www.nyse.com/trade/hours-calendars",
    "https://www.nyse.com/publicdocs/nyse/markets/american-options/rule-interpretations/2025/National_Day_of_Mourning_20250102.pdf",
)
_MAX_ROW_ERRORS = 64
_NUMERIC_FIELDS: dict[DatasetCategory, tuple[str, ...]] = {
    DatasetCategory.UNDERLYING_BARS: ("open", "high", "low", "close", "volume"),
    DatasetCategory.OPTION_QUOTES: ("strike", "bid", "ask"),
    DatasetCategory.OPTION_TRADES: ("strike", "price", "volume"),
    DatasetCategory.OPEN_INTEREST: ("open_interest",),
}


@dataclass(frozen=True)
class LeanFileInspection:
    data_file: DataFile
    session_dates: frozenset[date]
    available_at: tuple[datetime, ...]


class UnsupportedLeanDataFormat(ValueError):
    pass


class LeanDataAdapter:
    """Object facade used by services that prefer an adapter boundary."""

    def inspect_file(self, path: Path, category: DatasetCategory) -> LeanFileInspection:
        return inspect_lean_file(path, category)

    def build_manifest(
        self,
        *,
        dataset_id: str,
        dataset_root: Path,
        files: Iterable[DataFile],
        output_path: Path,
        fixture: bool = False,
    ) -> tuple[dict[str, Any], str]:
        return build_canonical_manifest(
            dataset_id=dataset_id,
            dataset_root=dataset_root,
            files=files,
            output_path=output_path,
            fixture=fixture,
        )

    def validate_sessions(
        self,
        inspections: Iterable[LeanFileInspection],
        *,
        requested_start: date,
        requested_end: date,
        symbols: Iterable[str],
    ) -> list[str]:
        return validate_session_coverage(
            inspections,
            requested_start=requested_start,
            requested_end=requested_end,
            symbols=symbols,
        )

    def stage_for_lean(
        self,
        *,
        dataset_root: Path,
        manifest_path: Path,
        output_parent: Path,
    ) -> "LeanStagingResult":
        """Convert a verified run manifest into LEAN's read-only data tree."""

        from stocks_tool.adapters.backtesting.lean_staging import stage_registered_dataset

        return stage_registered_dataset(dataset_root, manifest_path, output_parent)


def inspect_lean_file(path: Path, category: DatasetCategory) -> LeanFileInspection:
    """Validate one canonical CSV and return observed coverage metadata."""

    if path.suffix.lower() != ".csv":
        raise UnsupportedLeanDataFormat(f"unsupported LEAN source format: {path.name}")
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise UnsupportedLeanDataFormat(f"unreadable LEAN source: {path.name}") from exc
    with handle:
        reader = csv.DictReader(handle)
        original_fields = [str(value or "") for value in (reader.fieldnames or [])]
        raw_fields = [value.strip().lower().replace("-", "_") for value in original_fields]
        normalized_columns = {canonical: _find_column(raw_fields, aliases) for canonical, aliases in _ALIASES.items()}
        columns = {
            canonical: original_fields[raw_fields.index(value)] if value is not None else None
            for canonical, value in normalized_columns.items()
        }
        errors = [f"missing_column:{name}" for name in _REQUIRED[category] if columns.get(name) is None]
        symbols: set[str] = set()
        session_dates: set[date] = set()
        available: list[datetime] = []
        row_count = 0
        observed_dates: list[date] = []
        row_errors: list[str] = []
        row_error_count = 0
        invalid_rows = 0
        for row_index, row in enumerate(reader, start=2):
            row_count += 1
            symbol = _clean(row.get(columns["symbol"]) if columns.get("symbol") else None)
            if symbol:
                symbols.add(symbol.upper())
            row_error_start = row_error_count
            date_column = columns.get("date") or columns.get("effective_start")
            observed_raw = row.get(date_column) if date_column else None
            observed = _parse_date(observed_raw)
            if observed:
                observed_dates.append(observed)
                session_dates.add(observed)
            elif "date" in _REQUIRED[category] or "effective_start" in _REQUIRED[category]:
                row_error_count = _row_error(row_errors, row_error_count, row_index, "invalid_date")
            if "symbol" in _REQUIRED[category] and not symbol:
                row_error_count = _row_error(row_errors, row_error_count, row_index, "missing_symbol")
            available_raw = row.get(columns["available_at"]) if columns.get("available_at") else None
            available_at = _parse_datetime(available_raw)
            if available_at:
                available.append(available_at)
                cutoff = _availability_cutoff(observed_raw, row, column_name=date_column, category=category)
                if cutoff is not None and category in {
                    DatasetCategory.UNDERLYING_BARS,
                    DatasetCategory.OPTION_QUOTES,
                    DatasetCategory.OPTION_TRADES,
                    DatasetCategory.OPEN_INTEREST,
                    DatasetCategory.SECURITY_MASTER,
                    DatasetCategory.CORPORATE_ACTIONS,
                } and available_at > cutoff:
                    row_error_count = _row_error(
                        row_errors,
                        row_error_count,
                        row_index,
                        "availability_after_bar_end",
                    )
            elif "available_at" in _REQUIRED[category]:
                row_error_count = _row_error(
                    row_errors,
                    row_error_count,
                    row_index,
                    "missing_or_invalid_available_at",
                )
            for field in _NUMERIC_FIELDS.get(category, ()):
                numeric = _parse_decimal(row.get(columns[field]) if columns.get(field) else None)
                if numeric is None or numeric < 0:
                    row_error_count = _row_error(
                        row_errors,
                        row_error_count,
                        row_index,
                        f"invalid_nonnegative_{field}",
                    )
            if category is DatasetCategory.UNDERLYING_BARS:
                values = {
                    field: _parse_decimal(row.get(columns[field]) if columns.get(field) else None)
                    for field in ("open", "high", "low", "close")
                }
                if all(value is not None for value in values.values()):
                    if values["high"] < max(values["open"], values["close"], values["low"]):
                        row_error_count = _row_error(row_errors, row_error_count, row_index, "high_below_observed_price")
                    if values["low"] > min(values["open"], values["close"], values["high"]):
                        row_error_count = _row_error(row_errors, row_error_count, row_index, "low_above_observed_price")
            if category is DatasetCategory.OPTION_QUOTES:
                bid = _parse_decimal(row.get(columns["bid"]) if columns.get("bid") else None)
                ask = _parse_decimal(row.get(columns["ask"]) if columns.get("ask") else None)
                if bid is not None and ask is not None and ask < bid:
                    row_error_count = _row_error(row_errors, row_error_count, row_index, "ask_below_bid")
            if category in {DatasetCategory.OPTION_QUOTES, DatasetCategory.OPTION_TRADES}:
                right = _clean(row.get(columns["right"]) if columns.get("right") else None).lower()
                if right not in {"call", "put", "c", "p"}:
                    row_error_count = _row_error(row_errors, row_error_count, row_index, "invalid_option_right")
                expiration = _parse_date(row.get(columns["expiration"]) if columns.get("expiration") else None)
                if expiration is None:
                    row_error_count = _row_error(row_errors, row_error_count, row_index, "invalid_expiration")
            if category is DatasetCategory.CALENDARS:
                if not _valid_clock(row.get(columns["session_open"]) if columns.get("session_open") else None):
                    row_error_count = _row_error(row_errors, row_error_count, row_index, "invalid_session_open")
                if not _valid_clock(row.get(columns["session_close"]) if columns.get("session_close") else None):
                    row_error_count = _row_error(row_errors, row_error_count, row_index, "invalid_session_close")
            if category is DatasetCategory.SECURITY_MASTER:
                if not _clean(row.get(columns["security_type"]) if columns.get("security_type") else None):
                    row_error_count = _row_error(row_errors, row_error_count, row_index, "missing_security_type")
            if category is DatasetCategory.CORPORATE_ACTIONS:
                if not _clean(row.get(columns["action"]) if columns.get("action") else None):
                    row_error_count = _row_error(row_errors, row_error_count, row_index, "missing_corporate_action")
            if row_error_count > row_error_start:
                invalid_rows += 1
        if row_count == 0:
            errors.append("empty_file")
        errors.extend(row_errors)
        gaps: list[str] = []
        if "available_at" in _REQUIRED[category] and not available:
            errors.append("missing_point_in_time_availability")
        coverage_start = min(observed_dates) if observed_dates else None
        coverage_end = max(observed_dates) if observed_dates else None
        data_file = DataFile(
            path=path.name,
            category=category,
            sha256=_sha256(path),
            rows=row_count,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            availability_start=min(available) if available else None,
            availability_end=max(available) if available else None,
            symbols=sorted(symbols),
            sessions=len(session_dates),
            format="canonical_csv_v1",
            schema_valid=not errors,
            schema_errors=errors,
            coverage_gaps=gaps,
            invalid_rows=invalid_rows,
            row_error_count=row_error_count,
            size_bytes=path.stat().st_size,
        )
    return LeanFileInspection(
        data_file=data_file,
        session_dates=frozenset(session_dates),
        available_at=tuple(available),
    )


def build_canonical_manifest(
    *,
    dataset_id: str,
    dataset_root: Path,
    files: Iterable[DataFile],
    output_path: Path,
    fixture: bool = False,
) -> tuple[dict[str, Any], str]:
    """Write a deterministic manifest for the LEAN custom-data algorithm."""

    entries: list[dict[str, Any]] = []
    for item in sorted(files, key=lambda value: value.path):
        if not item.schema_valid:
            raise UnsupportedLeanDataFormat(f"source schema is not canonical: {item.path}")
        if item.coverage_gaps:
            raise UnsupportedLeanDataFormat(f"source coverage has gaps: {item.path}")
        source = (dataset_root / item.path).resolve()
        try:
            source.relative_to(dataset_root.resolve())
        except ValueError as exc:
            raise UnsupportedLeanDataFormat(f"manifest path escapes data root: {item.path}") from exc
        if not source.is_file() or _is_reparse_point(source):
            raise UnsupportedLeanDataFormat(f"manifest source is not a regular local file: {item.path}")
        actual_hash = _sha256(source)
        if item.sha256 and actual_hash != item.sha256:
            raise UnsupportedLeanDataFormat(f"manifest hash changed for {item.path}")
        # Normalize before interpolation for Python 3.11 in the pinned LEAN
        # image: backslashes inside an f-string expression are a syntax error.
        lean_relative_path = str(item.path).replace("\\", "/")
        entries.append(
            {
                "category": item.category.value,
                "source": item.path,
                # The checked-in LEAN algorithm reads custom data beneath this
                # stable namespace; no source path is mounted outside /data.
                "lean_path": f"stocks_tool/{item.category.value}/{lean_relative_path}",
                "sha256": actual_hash,
                "format": item.format,
                "symbols": item.symbols,
                "coverage_start": item.coverage_start.isoformat() if item.coverage_start else None,
                "coverage_end": item.coverage_end.isoformat() if item.coverage_end else None,
                "availability_start": item.availability_start.isoformat() if item.availability_start else None,
                "availability_end": item.availability_end.isoformat() if item.availability_end else None,
            }
        )
    payload = {
        "schema_version": "lean-local-v1",
        "dataset_id": dataset_id,
        "fixture": fixture,
        "network": "disabled",
        "point_in_time": True,
        "files": entries,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return payload, digest


def validate_session_coverage(
    inspections: Iterable[LeanFileInspection],
    *,
    requested_start: date,
    requested_end: date,
    symbols: Iterable[str],
) -> list[str]:
    """Return explicit per-symbol/session gaps instead of trusting endpoints."""

    inspections = list(inspections)
    expected_symbols = {value.strip().upper() for value in symbols if value.strip()}
    calendar_sessions = set().union(
        *(inspection.session_dates for inspection in inspections if inspection.data_file.category is DatasetCategory.CALENDARS)
    )
    expected_sessions = trusted_us_exchange_sessions(requested_start, requested_end)
    if not expected_sessions:
        return ["calendar_sessions_unavailable"]
    gaps: list[str] = []
    supplied_sessions = {
        value for value in calendar_sessions if requested_start <= value <= requested_end
    }
    for missing in sorted(expected_sessions - supplied_sessions):
        gaps.append(f"calendar_missing_trusted_session:{missing.isoformat()}")
    for extra in sorted(supplied_sessions - expected_sessions):
        gaps.append(f"calendar_untrusted_extra_session:{extra.isoformat()}")
    required_categories = {
        DatasetCategory.UNDERLYING_BARS,
        DatasetCategory.OPTION_QUOTES,
        DatasetCategory.OPTION_TRADES,
        DatasetCategory.OPEN_INTEREST,
    }
    for category in required_categories:
        category_inspections = [item for item in inspections if item.data_file.category is category]
        for symbol in sorted(expected_symbols):
            observed = set().union(
                *(item.session_dates for item in category_inspections if symbol in item.data_file.symbols)
            )
            missing = sorted(expected_sessions - observed)
            if missing:
                gaps.append(
                    f"{category.value}:{symbol}:missing_sessions={len(missing)}:first={missing[0].isoformat()}:last={missing[-1].isoformat()}"
                )
    return gaps


def trusted_us_exchange_sessions(start: date, end: date) -> set[date]:
    """Return deterministic NYSE regular sessions for the requested dates.

    This is the application's trusted exchange-calendar rule set; a supplied
    dataset calendar is evidence checked against it, never the authority that
    defines the expected session universe.
    """

    if end < start:
        return set()
    holidays: set[date] = set()
    for year in range(start.year - 1, end.year + 2):
        holidays.update(_nyse_holidays(year))
    sessions: set[date] = set()
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5 and cursor not in holidays:
            sessions.add(cursor)
        cursor += timedelta(days=1)
    return sessions


def trusted_session_close_utc(day: date) -> datetime:
    """Return the trusted NYSE regular/early close for a session date."""

    close_hour = 13 if _is_nyse_early_close(day) else 16
    eastern = datetime.combine(day, time(close_hour, 0), tzinfo=ZoneInfo("America/New_York"))
    return eastern.astimezone(timezone.utc)


def trusted_event_start_utc(day: date) -> datetime:
    """Conservative causal cutoff for effective-date events."""

    eastern = datetime.combine(day, time(0, 0), tzinfo=ZoneInfo("America/New_York"))
    return eastern.astimezone(timezone.utc)


def _availability_cutoff(
    value: Any,
    row: dict[str, Any],
    *,
    column_name: str | None = None,
    category: DatasetCategory | str | None = None,
) -> datetime | None:
    observed_datetime = _parse_datetime(value)
    category_name = str(getattr(category, "value", category) or "").lower()
    if category_name in {DatasetCategory.SECURITY_MASTER.value, DatasetCategory.CORPORATE_ACTIONS.value}:
        observed_date = _parse_date(value)
        return trusted_event_start_utc(observed_date) if observed_date else None
    if observed_datetime is None:
        observed_date = _parse_date(value)
        return trusted_session_close_utc(observed_date) if observed_date else None
    resolution = _clean(row.get("resolution")).lower()
    source = _clean(row.get("__source")).lower()
    normalized_column = _clean(column_name).lower().replace("-", "_")
    has_intraday_time = normalized_column in {"timestamp", "datetime", "time"}
    if resolution in {"minute", "min"} or "minute" in source or has_intraday_time:
        return observed_datetime + timedelta(minutes=1)
    return trusted_session_close_utc(observed_datetime.date())


def availability_cutoff(
    value: Any,
    row: dict[str, Any],
    *,
    column_name: str | None = None,
    category: DatasetCategory | str | None = None,
) -> datetime | None:
    """Public causal cutoff shared by validation and LEAN staging."""

    return _availability_cutoff(value, row, column_name=column_name, category=category)


def _is_nyse_early_close(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    # NYSE's recurring 13:00 ET holidays: the Friday after Thanksgiving,
    # Christmas Eve when it is a weekday, and July 3 when it is a weekday.
    if day.month == 11 and day.weekday() == 4:
        thanksgiving = _nth_weekday(day.year, 11, 3, 4)
        return day == thanksgiving + timedelta(days=1)
    if day.month == 12 and day.day == 24:
        return True
    if day.month == 7 and day.day == 3:
        return True
    return False


def _nyse_holidays(year: int) -> set[date]:
    holidays = {
        _observed_fixed(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _last_weekday(year, 5, 0),  # Memorial Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed_fixed(year, 12, 25),
        _easter_sunday(year) - timedelta(days=2),  # Good Friday
    }
    if year >= 2022:
        holidays.add(_observed_fixed(year, 6, 19))
    holidays.add(_observed_fixed(year, 7, 4))
    if year == 2025:
        # National Day of Mourning for former President Jimmy Carter.
        holidays.add(date(2025, 1, 9))
    return holidays


def _observed_fixed(year: int, month: int, day: int) -> date:
    value = date(year, month, day)
    # NYSE does not observe New Year's Day on the preceding Friday when
    # January 1 falls on Saturday; 2021-12-31 was an open session.
    if month == 1 and day == 1 and value.weekday() == 5:
        return value
    if value.weekday() == 5:
        return value - timedelta(days=1)
    if value.weekday() == 6:
        return value + timedelta(days=1)
    return value


def _nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> date:
    value = date(year, month, 1)
    offset = (weekday - value.weekday()) % 7
    return value + timedelta(days=offset + (ordinal - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        value = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        value = date(year, month + 1, 1) - timedelta(days=1)
    return value - timedelta(days=(value.weekday() - weekday) % 7)


def _easter_sunday(year: int) -> date:
    # Anonymous Gregorian computus, fixed and auditable for exchange dates.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _find_column(fields: list[str], aliases: tuple[str, ...]) -> str | None:
    for alias in aliases:
        if alias in fields:
            return alias
    return None


def _row_error(errors: list[str], total: int, row_index: int, code: str) -> int:
    total += 1
    if len(errors) < _MAX_ROW_ERRORS:
        errors.append(f"row:{row_index}:{code}")
    return total


def _parse_decimal(value: Any) -> Decimal | None:
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _valid_clock(value: Any) -> bool:
    text = _clean(value)
    if not text:
        return False
    try:
        datetime.strptime(text[:8], "%H:%M:%S")
        return True
    except ValueError:
        try:
            datetime.strptime(text[:5], "%H:%M")
            return True
        except ValueError:
            return False


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _parse_date(value: Any) -> date | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        parsed = _parse_datetime(text)
        return parsed.date() if parsed else None


def _parse_datetime(value: Any) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo("America/New_York"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)()):
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & 0x400)
