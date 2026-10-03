"""Local-only data-set inspection and hashing.

The inspector reads files that already exist below a dedicated allowlisted
root.  It never downloads, extracts, follows an external manifest as a
source of truth, or treats declared coverage as observed coverage.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from stocks_tool.domain.backtesting import (
    BACKTEST_DEFAULT_END,
    BACKTEST_DEFAULT_START,
    BACKTEST_SYMBOL_ALLOWLIST,
    DataFile,
    DatasetCategory,
    DatasetManifest,
    DatasetRegistration,
)
from stocks_tool.adapters.backtesting.lean_data import (
    UnsupportedLeanDataFormat,
    inspect_lean_file,
)


SUPPORTED_SUFFIXES = frozenset({".csv", ".json", ".jsonl", ".ndjson"})
FORBIDDEN_FILENAMES = frozenset({".env", ".env.local", ".env.production", ".env.development"})
_DATE_KEYS = ("date", "timestamp", "time", "datetime", "trading_date", "event_date", "as_of")


class DatasetSecurityError(ValueError):
    pass


class DatasetInspection:
    def __init__(self, *, allowed_root: Path) -> None:
        raw_root = Path(allowed_root).expanduser()
        if raw_root.exists() and _is_reparse_point(raw_root):
            raise DatasetSecurityError("dedicated backtest data root may not be a reparse point")
        self.allowed_root = raw_root.resolve()

    def resolve_dataset_root(self, value: str | os.PathLike[str]) -> Path:
        raw = str(value)
        if "://" in raw:
            raise DatasetSecurityError("dataset path must be local; network URLs are not allowed")
        raw_candidate = Path(raw).expanduser()
        if raw_candidate.exists() and _is_reparse_point(raw_candidate):
            raise DatasetSecurityError("dataset root may not be a symlink")
        candidate = raw_candidate.resolve(strict=False)
        if candidate == self.allowed_root:
            raise DatasetSecurityError("dataset root must be a child of the dedicated backtest data root")
        try:
            candidate.relative_to(self.allowed_root)
        except ValueError as exc:
            raise DatasetSecurityError("dataset path escapes the dedicated backtest data root") from exc
        if any(part.lower() in FORBIDDEN_FILENAMES for part in candidate.parts):
            raise DatasetSecurityError("dataset path may not contain environment files")
        if candidate.exists() and not candidate.is_dir():
            raise DatasetSecurityError("dataset path must be a directory")
        return candidate

    def inspect(
        self,
        registration: DatasetRegistration,
        *,
        root: Path | None = None,
    ) -> tuple[DatasetManifest, str, list[str], list[str]]:
        root = root or self.resolve_dataset_root(registration.root_path)
        if not root.exists():
            return (
                DatasetManifest(
                    provider=registration.provider,
                    license=registration.license,
                    provenance=registration.provenance,
                    declared_symbols=registration.symbols,
                    declared_start=registration.declared_start,
                    declared_end=registration.declared_end,
                ),
                hashlib.sha256(b"").hexdigest(),
                [],
                ["dataset_root_missing"],
            )
        files: list[DataFile] = []
        warnings: list[str] = []
        errors: list[str] = []
        resolved_root = root.resolve(strict=True)
        try:
            resolved_root.relative_to(self.allowed_root)
        except ValueError as exc:
            raise DatasetSecurityError("dataset root escapes the dedicated backtest data root") from exc
        for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            for directory in list(directories):
                directory_path = current_path / directory
                if _is_reparse_point(directory_path):
                    errors.append(f"reparse_point_not_allowed:{directory_path.relative_to(root).as_posix()}")
                    directories.remove(directory)
            for filename in sorted(filenames):
                path = current_path / filename
                if _is_reparse_point(path):
                    errors.append(f"reparse_point_not_allowed:{path.relative_to(root).as_posix()}")
                    continue
                try:
                    resolved_file = path.resolve(strict=True)
                    resolved_file.relative_to(resolved_root)
                    resolved_file.relative_to(self.allowed_root)
                except (OSError, ValueError):
                    errors.append(f"path_escapes_allowlist:{path.relative_to(root).as_posix()}")
                    continue
                relative = path.relative_to(root)
                if any(part.lower() in FORBIDDEN_FILENAMES for part in relative.parts):
                    errors.append(f"forbidden_file:{relative.as_posix()}")
                    continue
                if path.suffix.lower() in {".zip", ".tar", ".gz", ".7z"}:
                    errors.append(f"archive_not_allowed:{relative.as_posix()}")
                    continue
                if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                    warnings.append(f"unsupported_file:{relative.as_posix()}")
                    continue
                category = classify_file(path)
                if category is None:
                    warnings.append(f"unclassified_file:{relative.as_posix()}")
                    continue
                try:
                    inspection = inspect_lean_file(path, category)
                    data_file = inspection.data_file.model_copy(update={"path": relative.as_posix()})
                    files.append(data_file)
                    for error in data_file.schema_errors + data_file.coverage_gaps:
                        errors.append(f"{relative.as_posix()}:{error}")
                except UnsupportedLeanDataFormat as exc:
                    errors.append(f"{relative.as_posix()}:unsupported_format:{exc}")
        manifest = DatasetManifest(
            provider=registration.provider,
            license=registration.license,
            provenance=registration.provenance,
            files=files,
            declared_symbols=registration.symbols,
            declared_start=registration.declared_start,
            declared_end=registration.declared_end,
            notes=warnings,
        )
        data_hash = hash_manifest_files(files)
        return manifest, data_hash, warnings, errors


def classify_file(path: Path) -> DatasetCategory | None:
    name = path.name.lower().replace("-", "_")
    if "security" in name or "master" in name or name.startswith("symbols"):
        return DatasetCategory.SECURITY_MASTER
    if "open_interest" in name or "openinterest" in name or name.endswith("_oi.csv"):
        return DatasetCategory.OPEN_INTEREST
    if "calendar" in name or "trading_day" in name or "exchange_day" in name:
        return DatasetCategory.CALENDARS
    if "corporate" in name or "dividend" in name or "split" in name or "adjustment" in name:
        return DatasetCategory.CORPORATE_ACTIONS
    if "option" in name and ("quote" in name or "bid" in name or "ask" in name):
        return DatasetCategory.OPTION_QUOTES
    if "option" in name and ("trade" in name or "tick" in name):
        return DatasetCategory.OPTION_TRADES
    if "quote" in name and ("option" in name or "contract" in name):
        return DatasetCategory.OPTION_QUOTES
    if "trade" in name and ("option" in name or "contract" in name):
        return DatasetCategory.OPTION_TRADES
    if "underlying" in name or "equity" in name or "daily" in name or "bars" in name:
        return DatasetCategory.UNDERLYING_BARS
    return None


def sha256_file(path: Path) -> str:
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
    return bool(attributes & 0x400)  # Windows FILE_ATTRIBUTE_REPARSE_POINT


def hash_manifest_files(files: list[DataFile]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda value: value.path):
        digest.update(item.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update((item.sha256 or "").encode("ascii"))
        digest.update(b"\0")
        digest.update(item.category.value.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def inspect_content(path: Path) -> tuple[int | None, date | None, date | None, str | None]:
    try:
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    return 0, None, None, "missing_header"
                return _scan_rows(reader)
        if path.suffix.lower() in {".jsonl", ".ndjson"}:
            def rows():
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        if line.strip():
                            value = json.loads(line)
                            if isinstance(value, dict):
                                yield value
            return _scan_rows(rows())
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            value = value.get("rows") or value.get("data") or [value]
        if not isinstance(value, list):
            return None, None, None, "json_rows_not_array"
        return _scan_rows(value)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return None, None, None, f"unreadable:{type(exc).__name__}"


def _scan_rows(rows) -> tuple[int, date | None, date | None, str | None]:
    count = 0
    dates: list[date] = []
    for row in rows:
        count += 1
        if not isinstance(row, dict):
            continue
        for key in _DATE_KEYS:
            if row.get(key) in (None, ""):
                continue
            parsed = _parse_date(row[key])
            if parsed is not None:
                dates.append(parsed)
                break
    return count, (min(dates) if dates else None), (max(dates) if dates else None), None


def _parse_date(value: Any) -> date | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return None
