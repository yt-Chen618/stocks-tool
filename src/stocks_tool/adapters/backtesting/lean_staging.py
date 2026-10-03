"""Stage the registered canonical CSV contract into LEAN's local layout.

The application stores canonical, point-in-time CSVs so validation and hashes
remain provider-independent.  LEAN consumes a different on-disk contract:
compressed equity bars, option minute files, and option universe files.  This
module is the adapter between those contracts.  It never downloads data and
it writes only to a run-owned staging directory.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")


class LeanStagingError(RuntimeError):
    pass


@dataclass(frozen=True)
class LeanStagingResult:
    root: Path
    source_manifest_hash: str
    files_created: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    fixture_consumed: bool = False
    warnings: tuple[str, ...] = ()


def stage_registered_dataset(
    dataset_root: Path,
    manifest_path: Path,
    output_parent: Path,
) -> LeanStagingResult:
    """Stage a registered dataset and return the read-only mount root.

    ``manifest_path`` is the run-local canonical manifest produced by the
    application service.  A matching marker makes repeated launcher identity
    checks idempotent.  No existing staging tree is deleted.
    """

    dataset_root = Path(dataset_root).resolve()
    manifest_path = Path(manifest_path).resolve()
    output_parent = Path(output_parent).resolve()
    if not dataset_root.is_dir():
        raise LeanStagingError("registered dataset root is not a directory")
    if not manifest_path.is_file():
        raise LeanStagingError("registered dataset manifest is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise LeanStagingError("registered dataset manifest is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise LeanStagingError("registered dataset manifest has no files list")
    manifest_hash = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    staging_root = output_parent / "lean-data-staged"
    marker_path = staging_root / "stocks-tool-staging.json"
    if marker_path.is_file():
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise LeanStagingError("existing LEAN staging marker is unreadable") from exc
        if marker.get("source_manifest_hash") != manifest_hash:
            raise LeanStagingError("existing LEAN staging belongs to a different dataset manifest")
        if marker.get("schema_version") != "lean-staging-v2":
            raise LeanStagingError("existing LEAN staging uses an obsolete schema; regenerate the run-owned staging directory")
        return LeanStagingResult(
            root=staging_root,
            source_manifest_hash=manifest_hash,
            files_created=tuple(marker.get("files_created") or ()),
            symbols=tuple(marker.get("symbols") or ()),
            fixture_consumed=bool(marker.get("fixture_consumed")),
            warnings=tuple(marker.get("warnings") or ()),
        )

    staging_root.mkdir(parents=True, exist_ok=True)
    rows_by_category: dict[str, list[dict[str, str]]] = defaultdict(list)
    warnings: list[str] = []
    for entry in manifest["files"]:
        if not isinstance(entry, dict):
            raise LeanStagingError("dataset manifest contains a non-object file entry")
        relative = str(entry.get("source") or "").replace("\\", "/")
        source = _safe_child(dataset_root, relative)
        if not source.is_file() or source.is_symlink():
            raise LeanStagingError(f"registered dataset source is missing: {relative}")
        category = str(entry.get("category") or "").lower()
        rows = _read_csv(source)
        for row in rows:
            row["__source"] = relative
        rows_by_category[category].extend(rows)

    files_created: list[str] = []
    underlying = rows_by_category.get("underlying_bars", [])
    underlying, rejected_underlying = _causal_rows(underlying, "underlying_bars")
    if rejected_underlying:
        warnings.append(f"future_information_rejected:underlying_bars:{rejected_underlying}")
    symbols = sorted({_native_symbol(row.get("symbol") or row.get("ticker") or "") for row in underlying if _native_symbol(row.get("symbol") or row.get("ticker") or "")})
    if underlying:
        files_created.extend(_write_equity_daily(staging_root, underlying))
        minute_rows = [row for row in underlying if _is_minute_row(row)]
        if minute_rows:
            minute_files = _write_equity_minute(staging_root, minute_rows)
            files_created.extend(minute_files)
            if not any(path.endswith("_quote.zip") for path in minute_files):
                warnings.append("equity_quote_unavailable")
        else:
            warnings.append("minute_equity_unavailable")
        if _write_fixture_bridge(staging_root, underlying):
            files_created.append("custom/stocks-tool-fixture.csv")
        if bool(manifest.get("fixture")):
            # A software fixture must not inherit the image's market-data
            # factors or symbol mappings after the asset subtree is mounted
            # over /Lean/Data. Emit explicit identity files for this
            # synthetic-only path; real datasets must provide validated
            # corporate-action/security-master inputs instead.
            neutral_files = _write_fixture_neutral_auxiliary(staging_root, underlying)
            files_created.extend(neutral_files)
            if neutral_files:
                warnings.append("fixture_neutral_factor_map")
    else:
        warnings.append("underlying_bars_unavailable")

    option_rows = rows_by_category.get("option_quotes", [])
    option_rows += rows_by_category.get("option_trades", [])
    option_rows += rows_by_category.get("open_interest", [])
    option_rows, rejected_options = _causal_rows(option_rows, "options")
    if rejected_options:
        warnings.append(f"future_information_rejected:options:{rejected_options}")
    if option_rows:
        option_files = _write_option_files(staging_root, option_rows)
        files_created.extend(option_files)
        if not any("_quote_american.zip" in path for path in option_files):
            warnings.append("option_quote_unavailable")
        elif not any(_has_explicit_quote_size(row) for row in option_rows):
            warnings.append("option_quote_size_unavailable")
    else:
        warnings.append("option_files_unavailable")

    corporate_actions = rows_by_category.get("corporate_actions", [])
    if corporate_actions:
        factor_files, action_warnings = _write_factor_files(
            staging_root,
            corporate_actions,
            underlying,
        )
        files_created.extend(factor_files)
        warnings.extend(action_warnings)
    else:
        warnings.append("corporate_actions_unavailable")

    security_master = rows_by_category.get("security_master", [])
    if security_master:
        map_files, master_warnings = _write_map_files(staging_root, security_master)
        files_created.extend(map_files)
        warnings.extend(master_warnings)
    else:
        warnings.append("security_master_unavailable")

    marker = {
        "schema_version": "lean-staging-v2",
        "source_manifest_hash": manifest_hash,
        "files_created": sorted(set(files_created)),
        "symbols": symbols,
        "fixture_consumed": "custom/stocks-tool-fixture.csv" in files_created,
        "warnings": sorted(set(warnings)),
    }
    marker_path.write_text(json.dumps(marker, sort_keys=True, indent=2), encoding="utf-8")
    return LeanStagingResult(
        root=staging_root,
        source_manifest_hash=manifest_hash,
        files_created=tuple(marker["files_created"]),
        symbols=tuple(symbols),
        fixture_consumed=bool(marker["fixture_consumed"]),
        warnings=tuple(marker["warnings"]),
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [{str(key or "").strip().lower(): str(value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise LeanStagingError(f"canonical CSV cannot be read: {path.name}") from exc


def _safe_child(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise LeanStagingError("manifest source path must be relative")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise LeanStagingError("manifest source path escapes the dataset root") from exc
    return candidate


def _native_symbol(value: str) -> str:
    value = str(value or "").strip().upper()
    return value.split(".", 1)[0]


def _parse_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return None


def _parse_datetime(value: str, fallback: date | None = None) -> datetime | None:
    text = str(value or "").strip()
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=NEW_YORK)
        except ValueError:
            pass
    return datetime.combine(fallback, datetime.min.time(), NEW_YORK) if fallback else None


def _local_moment(value: str, fallback: date | None = None) -> datetime | None:
    parsed = _parse_datetime(value, fallback)
    if parsed is None:
        return None
    return parsed.astimezone(NEW_YORK)


def _session_date(row: Mapping[str, str]) -> date | None:
    moment = _local_moment(row.get("timestamp") or row.get("date"))
    return moment.date() if moment is not None else None


def _decimal(value: str, default: Decimal | None = None) -> Decimal | None:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return default


def _scaled_price(value: str, default: Decimal = Decimal("0")) -> int:
    number = _decimal(value, default) or default
    return int((number * Decimal("10000")).quantize(Decimal("1")))


def _write_fixture_bridge(root: Path, rows: Iterable[Mapping[str, str]]) -> bool:
    values: list[tuple[date, Decimal]] = []
    for row in rows:
        observed = _session_date(row)
        close = _decimal(row.get("close") or row.get("price") or "")
        if observed and close is not None:
            values.append((observed, close))
    if not values:
        return False
    target = root / "custom" / "stocks-tool-fixture.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["timestamp,value"]
    lines.extend(f"{day.isoformat()} 00:00:00,{close}" for day, close in sorted(values))
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def _write_fixture_neutral_auxiliary(root: Path, rows: Iterable[Mapping[str, str]]) -> list[str]:
    """Write identity map/factor inputs for synthetic fixture assets only."""

    by_symbol: dict[str, list[date]] = defaultdict(list)
    for row in rows:
        symbol = _native_symbol(row.get("symbol") or row.get("ticker") or "")
        day = _session_date(row)
        if symbol and day is not None:
            by_symbol[symbol].append(day)

    created: list[str] = []
    newline = chr(10)
    for symbol, days in sorted(by_symbol.items()):
        first_day = min(days).strftime("%Y%m%d")
        factor_relative = Path("equity") / "usa" / "factor_files" / f"{symbol.lower()}.csv"
        factor_target = root / factor_relative
        factor_target.parent.mkdir(parents=True, exist_ok=True)
        factor_target.write_text(
            f"{first_day},1,1,0{newline}20501231,1,1,0{newline}",
            encoding="utf-8",
        )
        created.append(factor_relative.as_posix())

        map_relative = Path("equity") / "usa" / "map_files" / f"{symbol.lower()}.csv"
        map_target = root / map_relative
        map_target.parent.mkdir(parents=True, exist_ok=True)
        map_target.write_text(
            f"{first_day},{symbol.lower()},P{newline}20501231,{symbol.lower()},P{newline}",
            encoding="utf-8",
        )
        created.append(map_relative.as_posix())
    return created


def _causal_rows(rows: Iterable[Mapping[str, str]], label: str) -> tuple[list[dict[str, str]], int]:
    from stocks_tool.adapters.backtesting.lean_data import availability_cutoff

    accepted: list[dict[str, str]] = []
    rejected = 0
    for original in rows:
        row = dict(original)
        if label == "security_master":
            observed_value = row.get("effective_start") or row.get("start_date") or row.get("date")
        elif label == "corporate_actions":
            observed_value = row.get("effective_date") or row.get("date") or row.get("timestamp")
        else:
            observed_value = row.get("timestamp") or row.get("date")
        observed = _parse_datetime(observed_value)
        available = _parse_datetime(row.get("available_at") or row.get("as_of"))
        # Native LEAN bars are emitted at the observation timestamp and cannot
        # represent a later publication time.  Reject such rows instead of
        # silently replaying information that was unavailable at the bar.
        cutoff = availability_cutoff(
            observed_value,
            row,
            column_name="timestamp" if row.get("timestamp") else "date",
            category=label,
        )
        if cutoff is not None and available is not None and available > cutoff:
            rejected += 1
            continue
        accepted.append(row)
    return accepted, rejected


def _is_minute_row(row: Mapping[str, str]) -> bool:
    resolution = str(row.get("resolution") or "").strip().lower()
    source = str(row.get("__source") or "").lower()
    return resolution in {"minute", "min"} or "minute" in source


def _write_equity_daily(root: Path, rows: Iterable[Mapping[str, str]]) -> list[str]:
    grouped: dict[tuple[str, date], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        symbol = _native_symbol(row.get("symbol") or row.get("ticker") or "")
        day = _session_date(row)
        close = _decimal(row.get("close") or "")
        if not symbol or day is None or close is None:
            continue
        grouped[(symbol, day)].append(
            {
                "day": day,
                "open": row.get("open") or str(close),
                "high": row.get("high") or str(close),
                "low": row.get("low") or str(close),
                "close": str(close),
                "volume": row.get("volume") or "0",
            }
        )
    created: list[str] = []
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (symbol, day), values in grouped.items():
        ordered = sorted(values, key=lambda value: value["day"])
        by_symbol[symbol].append(
            {
                "day": day,
                "open": ordered[0]["open"],
                "high": max(_decimal(value["high"]) or Decimal("0") for value in ordered),
                "low": min(_decimal(value["low"]) or Decimal("0") for value in ordered),
                "close": ordered[-1]["close"],
                "volume": sum(int(float(value["volume"])) for value in ordered),
            }
        )
    for symbol, values in by_symbol.items():
        relative = Path("equity") / "usa" / "daily" / f"{symbol.lower()}.zip"
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        entry = f"{symbol.lower()}.csv"
        lines = [
            f"{item['day'].strftime('%Y%m%d')} 00:00,{_scaled_price(item['open'])},{_scaled_price(item['high'])},{_scaled_price(item['low'])},{_scaled_price(item['close'])},{int(float(item['volume']))}"
            for item in sorted(values, key=lambda value: value["day"])
        ]
        _write_zip(target, entry, "\n".join(lines) + "\n")
        created.append(relative.as_posix())
    return created


def _write_equity_minute(root: Path, rows: Iterable[Mapping[str, str]]) -> list[str]:
    grouped: dict[tuple[str, date], list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        symbol = _native_symbol(row.get("symbol") or row.get("ticker") or "")
        observed = _local_moment(row.get("timestamp") or row.get("date"))
        if symbol and observed:
            grouped[(symbol, observed.date())].append(row)
    created: list[str] = []
    for (symbol, day), values in grouped.items():
        relative = Path("equity") / "usa" / "minute" / symbol.lower() / f"{day.strftime('%Y%m%d')}_trade.zip"
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        quote_lines: list[str] = []
        for row in sorted(values, key=lambda item: _parse_datetime(item.get("timestamp") or item.get("date")) or datetime.min.replace(tzinfo=timezone.utc)):
            moment = _local_moment(row.get("timestamp") or row.get("date"), day) or datetime.combine(day, datetime.min.time(), NEW_YORK)
            milliseconds = (moment.hour * 3600 + moment.minute * 60 + moment.second) * 1000 + moment.microsecond // 1000
            close = row.get("close") or row.get("price") or "0"
            lines.append(
                f"{milliseconds},{_scaled_price(row.get('open') or close)},{_scaled_price(row.get('high') or close)},{_scaled_price(row.get('low') or close)},{_scaled_price(close)},{int(float(row.get('volume') or 0))}"
            )
            # A trade close and its volume are not a quote or displayed book
            # size.  Only stage a QuoteBar when the source supplied both sides
            # explicitly; missing sizes remain zero so a quote-size-aware fill
            # model refuses it instead of inventing liquidity.
            bid = _decimal(row.get("bid") or row.get("bid_price"))
            ask = _decimal(row.get("ask") or row.get("ask_price"))
            if bid is not None and ask is not None and bid > 0 and ask >= bid:
                bid_size = _decimal(
                    row.get("bid_size") or row.get("last_bid_size") or row.get("bid_quantity")
                ) or Decimal("0")
                ask_size = _decimal(
                    row.get("ask_size") or row.get("last_ask_size") or row.get("ask_quantity")
                ) or Decimal("0")
                quote_lines.append(
                    f"{milliseconds},{_scaled_price(str(bid))},{_scaled_price(str(bid))},{_scaled_price(str(bid))},{_scaled_price(str(bid))},{int(bid_size)},{_scaled_price(str(ask))},{_scaled_price(str(ask))},{_scaled_price(str(ask))},{_scaled_price(str(ask))},{int(ask_size)}"
                )
        entry = f"{day.strftime('%Y%m%d')}_{symbol.lower()}_minute_trade.csv"
        _write_zip(target, entry, "\n".join(lines) + "\n")
        created.append(relative.as_posix())
        if quote_lines:
            quote_relative = Path("equity") / "usa" / "minute" / symbol.lower() / f"{day.strftime('%Y%m%d')}_quote.zip"
            quote_target = root / quote_relative
            quote_target.parent.mkdir(parents=True, exist_ok=True)
            quote_entry = f"{day.strftime('%Y%m%d')}_{symbol.lower()}_minute_quote.csv"
            _write_zip(quote_target, quote_entry, "\n".join(quote_lines) + "\n")
            created.append(quote_relative.as_posix())
    return created


def _write_option_files(root: Path, rows: Iterable[Mapping[str, str]]) -> list[str]:
    # Canonical options are staged into LEAN's documented minute quote/trade/
    # open-interest layout.  Rows lacking a contract identity are retained by
    # the dataset validator but cannot be silently converted into a security.
    grouped: dict[tuple[str, date, str, str, str], list[Mapping[str, str]]] = defaultdict(list)
    universe: dict[tuple[str, date], dict[tuple[str, str, str], Mapping[str, str]]] = defaultdict(dict)
    archives: dict[tuple[str, date, str], dict[str, str]] = defaultdict(dict)
    for row in rows:
        underlying = _native_symbol(row.get("underlying") or row.get("underlying_symbol") or "")
        day = _session_date(row)
        expiry = _parse_date(row.get("expiration") or row.get("expiry") or "")
        strike = _decimal(row.get("strike") or row.get("strike_price") or "")
        right = _right(row.get("right") or row.get("option_right") or "")
        if underlying and day and expiry and strike is not None and right:
            grouped[(underlying, day, expiry.isoformat(), str(strike), right)].append(row)
            universe[(underlying, day)][(expiry.isoformat(), str(strike), right)] = row
    created: list[str] = []
    for (underlying, day, expiry_text, strike_text, right), values in grouped.items():
        expiry = date.fromisoformat(expiry_text)
        strike = Decimal(str(strike_text))
        scale = int((strike * Decimal("10000")).quantize(Decimal("1")))
        by_kind: dict[str, list[str]] = defaultdict(list)
        for row in values:
            moment = _local_moment(row.get("timestamp") or row.get("date"), day) or datetime.combine(day, datetime.min.time(), NEW_YORK)
            milliseconds = (moment.hour * 3600 + moment.minute * 60 + moment.second) * 1000 + moment.microsecond // 1000
            bid_value = _decimal(row.get("bid") or row.get("bid_price"))
            ask_value = _decimal(row.get("ask") or row.get("ask_price"))
            price = _scaled_price(row.get("price") or row.get("trade_price") or row.get("close") or "0")
            volume = int(float(row.get("volume") or row.get("size") or "0"))
            oi = int(float(row.get("open_interest") or row.get("oi") or "0"))
            if bid_value is not None and ask_value is not None and bid_value > 0 and ask_value >= bid_value:
                bid = _scaled_price(str(bid_value))
                ask = _scaled_price(str(ask_value))
                bid_size = _decimal(
                    row.get("bid_size") or row.get("last_bid_size") or row.get("bid_quantity")
                ) or Decimal("0")
                ask_size = _decimal(
                    row.get("ask_size") or row.get("last_ask_size") or row.get("ask_quantity")
                ) or Decimal("0")
                by_kind["quote"].append(
                    f"{milliseconds},{bid},{bid},{bid},{bid},{int(bid_size)},{ask},{ask},{ask},{ask},{int(ask_size)}"
                )
            if row.get("price") or row.get("trade_price") or row.get("close"):
                by_kind["trade"].append(f"{milliseconds},{price},{price},{price},{price},{volume}")
            if row.get("open_interest") or row.get("oi"):
                by_kind["openinterest"].append(f"{milliseconds},{oi}")
        for kind, lines in by_kind.items():
            entry = f"{day.strftime('%Y%m%d')}_{underlying.lower()}_minute_{kind}_american_{right}_{scale}_{expiry.strftime('%Y%m%d')}.csv"
            archives[(underlying, day, kind)][entry] = "\n".join(lines) + "\n"
    for (underlying, day, kind), entries in archives.items():
        relative = Path("option") / "usa" / "minute" / underlying.lower() / f"{day.strftime('%Y%m%d')}_{kind}_american.zip"
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_zip_entries(target, entries)
        created.append(relative.as_posix())
    universe_header = "#expiry,strike,right,open,high,low,close,volume,open_interest,implied_volatility,delta,gamma,vega,theta,rho"
    for (underlying, day), contracts in universe.items():
        relative = Path("option") / "usa" / "universes" / underlying.lower() / f"{day.strftime('%Y%m%d')}.csv"
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = [universe_header]
        for (expiry, strike, right), row in sorted(contracts.items()):
            lines.append(
                ",".join(
                    [
                        expiry.replace("-", ""),
                        strike,
                        "C" if right == "call" else "P",
                        row.get("open") or row.get("bid") or row.get("price", ""),
                        row.get("high") or row.get("ask") or row.get("price", ""),
                        row.get("low") or row.get("bid") or row.get("price", ""),
                        row.get("close") or row.get("bid") or row.get("price", ""),
                        row.get("volume", ""),
                        row.get("open_interest", row.get("oi", "")),
                        row.get("implied_volatility", ""),
                        row.get("delta", ""),
                        row.get("gamma", ""),
                        row.get("vega", ""),
                        row.get("theta", ""),
                        row.get("rho", ""),
                    ]
                )
            )
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        created.append(relative.as_posix())
    return created


def _write_factor_files(
    root: Path,
    rows: Iterable[Mapping[str, str]],
    underlying_rows: Iterable[Mapping[str, str]],
) -> tuple[list[str], list[str]]:
    """Convert supported split/dividend actions into LEAN factor files.

    LEAN's equity factor rows are ``date,priceFactor,splitFactor,reference``.
    We emit one deterministic row per action and a terminal row. Unsupported
    corporate actions stay fail-closed through an explicit warning.
    """

    by_symbol_price: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)
    for row in underlying_rows:
        symbol = _native_symbol(row.get("symbol") or row.get("ticker") or "")
        day = _parse_date(row.get("date") or row.get("timestamp") or "")
        close = _decimal(row.get("close") or row.get("price") or "")
        if symbol and day and close is not None and close > 0:
            by_symbol_price[symbol].append((day, close))
    for values in by_symbol_price.values():
        values.sort(key=lambda item: item[0])

    actions_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    warnings: list[str] = []
    accepted, rejected = _causal_rows(rows, "corporate_actions")
    if rejected:
        warnings.append(f"future_information_rejected:corporate_actions:{rejected}")
    for original in accepted:
        row = dict(original)
        symbol = _native_symbol(row.get("symbol") or row.get("underlying") or row.get("ticker") or "")
        day = _parse_date(row.get("date") or row.get("effective_date") or row.get("timestamp") or "")
        action = _normalize_corporate_action(row.get("action") or row.get("event_type") or row.get("corporate_action") or "")
        if not symbol or day is None:
            warnings.append("corporate_actions_not_staged:unsupported:missing_symbol_or_date")
            continue
        if action not in {"split", "dividend"}:
            warnings.append(f"corporate_actions_not_staged:unsupported:{symbol}:{day.isoformat()}:{action or 'unknown'}")
            continue
        if action == "split":
            ratio = _action_decimal(row, ("split_factor", "ratio", "factor"))
            if ratio is None:
                ratio = _split_ratio_from_text(row.get("action") or "")
            if ratio is None or ratio <= 0:
                warnings.append(f"corporate_actions_not_staged:unsupported:{symbol}:{day.isoformat()}:split_ratio_missing")
                continue
            row["__ratio"] = str(ratio)
        else:
            amount = _action_decimal(row, ("distribution", "dividend", "amount", "cash_amount"))
            if amount is None or amount < 0:
                warnings.append(f"corporate_actions_not_staged:unsupported:{symbol}:{day.isoformat()}:dividend_amount_missing")
                continue
            row["__amount"] = str(amount)
        row["__day"] = day.isoformat()
        actions_by_symbol[symbol].append(row)

    created: list[str] = []
    for symbol, actions in sorted(actions_by_symbol.items()):
        prices = by_symbol_price.get(symbol, [])
        if not prices:
            warnings.append(f"corporate_actions_not_staged:unsupported:{symbol}:underlying_reference_missing")
            continue
        # FactorFileGenerator walks actions newest-to-oldest. Each generated
        # row is dated at the last trading day before the event, so the factor
        # applies to prices leading into the event. Same-day dividend+split is
        # applied as dividend first, then split, matching LEAN's intraday
        # combination path.
        actions_by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for row in actions:
            actions_by_day[date.fromisoformat(row["__day"])].append(row)
        price_factor = Decimal("1")
        split_factor = Decimal("1")
        factor_rows: dict[date, str] = {}
        for action_day in sorted(actions_by_day, reverse=True):
            previous = _previous_trading_close(prices, action_day)
            if previous is None or previous[1] <= 0:
                warnings.append(f"corporate_actions_not_staged:unsupported:{symbol}:{action_day.isoformat()}:reference_price_missing")
                continue
            previous_day, previous_close = previous
            day_actions = actions_by_day[action_day]
            for row in sorted(day_actions, key=lambda item: 0 if _normalize_corporate_action(item.get("action") or item.get("event_type") or item.get("corporate_action") or "") == "dividend" else 1):
                action = _normalize_corporate_action(row.get("action") or row.get("event_type") or row.get("corporate_action") or "")
                if action == "dividend":
                    distribution = Decimal(str(row["__amount"]))
                    price_factor *= max(Decimal("0"), Decimal("1") - distribution * split_factor / previous_close)
                elif action == "split":
                    split_factor /= Decimal(str(row["__ratio"]))
            factor_rows[previous_day] = (
                f"{previous_day.strftime('%Y%m%d')},{price_factor:.7f},{split_factor:.7f},{previous_close:g}"
            )
        # LEAN's terminal factor row is the fixed far-future identity row.
        factor_rows[date(2050, 12, 31)] = "20501231,1,1,0"
        lines = [factor_rows[key] for key in sorted(factor_rows)]
        relative = Path("equity") / "usa" / "factor_files" / f"{symbol.lower()}.csv"
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        created.append(relative.as_posix())
    if created:
        warnings.append(f"corporate_actions_staged:{len(created)}")
    return created, warnings


def _write_map_files(root: Path, rows: Iterable[Mapping[str, str]]) -> tuple[list[str], list[str]]:
    """Convert the security master into LEAN USA equity map files."""

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    warnings: list[str] = []
    accepted, rejected = _causal_rows(rows, "security_master")
    if rejected:
        warnings.append(f"future_information_rejected:security_master:{rejected}")
    for original in accepted:
        row = dict(original)
        symbol = _native_symbol(row.get("symbol") or row.get("ticker") or row.get("old_symbol") or "")
        start = _parse_date(row.get("effective_start") or row.get("start_date") or row.get("date") or "")
        mapped = _native_symbol(row.get("mapped_symbol") or row.get("new_symbol") or row.get("security_symbol") or row.get("symbol") or "")
        security_type = str(row.get("security_type") or row.get("asset_type") or "equity").strip().lower()
        if security_type not in {"equity", "stock", "etf"}:
            warnings.append(f"security_master_not_staged:unsupported_type:{symbol}:{security_type}")
            continue
        if not symbol or not mapped or start is None:
            warnings.append("security_master_not_staged:invalid:missing_symbol_or_effective_start")
            continue
        grouped[symbol].append({"start": start.isoformat(), "mapped": mapped})

    created: list[str] = []
    for symbol, entries in sorted(grouped.items()):
        entries.sort(key=lambda row: (row["start"], row["mapped"]))
        lines = [f"{entry['start'].replace('-', '')},{entry['mapped'].lower()},P" for entry in entries]
        if not lines:
            continue
        # LEAN map files use a far-future terminal date when no later mapping
        # is supplied, as shown by the official USA map files.
        last_mapped = entries[-1]["mapped"].lower()
        lines.append(f"20501231,{last_mapped},P")
        relative = Path("equity") / "usa" / "map_files" / f"{symbol.lower()}.csv"
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(dict.fromkeys(lines)) + "\n", encoding="utf-8")
        created.append(relative.as_posix())
    if created:
        warnings.append(f"security_master_staged:{len(created)}")
    return created, warnings


def _normalize_corporate_action(value: str) -> str:
    text = str(value or "").strip().lower()
    if "split" in text:
        return "split"
    if "dividend" in text or "distribution" in text:
        return "dividend"
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _action_decimal(row: Mapping[str, str], keys: tuple[str, ...]) -> Decimal | None:
    for key in keys:
        value = _decimal(row.get(key, ""))
        if value is not None:
            return value
    return None


def _split_ratio_from_text(value: str) -> Decimal | None:
    match = re.search(r"(?:split\s*)?([0-9]+(?:\.[0-9]+)?)\s*[:/]\s*([0-9]+(?:\.[0-9]+)?)", str(value or ""))
    if not match:
        return None
    numerator = _decimal(match.group(1))
    denominator = _decimal(match.group(2))
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _previous_trading_close(
    prices: list[tuple[date, Decimal]],
    action_day: date,
) -> tuple[date, Decimal] | None:
    prior = [(day, price) for day, price in prices if day < action_day]
    return prior[-1] if prior else None


def _right(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"c", "call"}:
        return "call"
    if text in {"p", "put"}:
        return "put"
    return ""


def _has_explicit_quote_size(row: Mapping[str, str]) -> bool:
    """Whether a canonical row carries both displayed quote sizes."""

    bid_size = _decimal(row.get("bid_size") or row.get("last_bid_size") or row.get("bid_quantity"))
    ask_size = _decimal(row.get("ask_size") or row.get("last_ask_size") or row.get("ask_quantity"))
    return bid_size is not None and ask_size is not None and bid_size > 0 and ask_size > 0


def _write_zip(path: Path, entry: str, content: str) -> None:
    _write_zip_entries(path, {entry: content})


def _write_zip_entries(path: Path, entries: Mapping[str, str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry, content in sorted(entries.items()):
            archive.writestr(entry, content.encode("utf-8"))
