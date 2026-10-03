"""Public domain contracts for offline historical backtests.

The backtesting surface is deliberately separate from the trading ledger.  A
backtest can read a registered, immutable data set and produce a result, but
it can never create an order, execution, or trading intent.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


BACKTEST_DEFAULT_START = date(2020, 1, 1)
BACKTEST_DEFAULT_END = date(2026, 9, 30)
BACKTEST_SYMBOL_ALLOWLIST = frozenset({"QQQ", "SPY", "SMH", "SOXL", "EWY", "AAPL"})


class DatasetStatus(StrEnum):
    REGISTERED = "registered"
    VALIDATING = "validating"
    VALID = "valid"
    BLOCKED_DATA = "blocked_data"
    INVALID = "invalid"


class BacktestState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    BLOCKED_DATA = "blocked_data"


class BacktestStrategy(StrEnum):
    BULL_PUT = "bull_put"
    COVERED_CALL = "covered_call"
    ZERO_DTE = "zero_dte"


class DatasetCategory(StrEnum):
    SECURITY_MASTER = "security_master"
    UNDERLYING_BARS = "underlying_bars"
    OPTION_QUOTES = "option_quotes"
    OPTION_TRADES = "option_trades"
    OPEN_INTEREST = "open_interest"
    CALENDARS = "calendars"
    CORPORATE_ACTIONS = "corporate_actions"


class DataFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    category: DatasetCategory
    sha256: str | None = None
    rows: int | None = Field(default=None, ge=0)
    coverage_start: date | None = None
    coverage_end: date | None = None
    availability_start: datetime | None = None
    availability_end: datetime | None = None
    symbols: list[str] = Field(default_factory=list)
    sessions: int | None = Field(default=None, ge=0)
    format: str = "canonical_csv_v1"
    schema_valid: bool = False
    schema_errors: list[str] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)
    invalid_rows: int = Field(default=0, ge=0)
    row_error_count: int = Field(default=0, ge=0)
    size_bytes: int | None = Field(default=None, ge=0)


class DatasetManifest(BaseModel):
    """The immutable evidence used to decide whether a run may start."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1"
    provider: str
    license: str
    provenance: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    files: list[DataFile] = Field(default_factory=list)
    declared_symbols: list[str] = Field(default_factory=list)
    declared_start: date | None = None
    declared_end: date | None = None
    notes: list[str] = Field(default_factory=list)

    @field_validator("declared_symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            symbol = value.strip().upper()
            if symbol and symbol not in result:
                result.append(symbol)
        return result


class DatasetRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1, max_length=160)
    root_path: str = Field(min_length=1, max_length=1024)
    provider: str = Field(min_length=1, max_length=160)
    license: str = Field(min_length=1, max_length=512)
    provenance: str = Field(min_length=1, max_length=1024)
    symbols: list[str] = Field(default_factory=list)
    declared_start: date = BACKTEST_DEFAULT_START
    declared_end: date = BACKTEST_DEFAULT_END
    manifest: DatasetManifest | None = None

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            symbol = value.strip().upper()
            if symbol and symbol not in result:
                result.append(symbol)
        return result

    @model_validator(mode="after")
    def validate_range(self) -> "DatasetRegistration":
        if self.declared_end < self.declared_start:
            raise ValueError("declared_end must be on or after declared_start")
        return self


class DatasetValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    status: DatasetStatus
    valid: bool
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    manifest_hash: str | None = None
    data_hash: str | None = None
    categories_present: list[DatasetCategory] = Field(default_factory=list)
    categories_required: list[DatasetCategory] = Field(default_factory=list)
    missing_categories: list[DatasetCategory] = Field(default_factory=list)
    coverage_start: date | None = None
    coverage_end: date | None = None
    requested_start: date | None = None
    requested_end: date | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    schema_errors: list[str] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)
    symbols_covered: list[str] = Field(default_factory=list)
    fixture: bool = False
    canonical_manifest_hash: str | None = None
    files: list[DataFile] = Field(default_factory=list)


class DatasetSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    root_path: str
    provider: str
    license: str
    provenance: str
    symbols: list[str] = Field(default_factory=list)
    declared_start: date
    declared_end: date
    status: DatasetStatus
    manifest_hash: str | None = None
    data_hash: str | None = None
    validation: DatasetValidationReport | None = None
    created_at: datetime
    updated_at: datetime


class FeeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    commission_per_contract: Decimal = Field(default=Decimal("0"), ge=0)
    commission_rate: Decimal = Field(default=Decimal("0"), ge=0)
    minimum_commission: Decimal = Field(default=Decimal("0"), ge=0)
    exchange_fee_per_contract: Decimal = Field(default=Decimal("0"), ge=0)


class SlippageModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    basis_points: Decimal = Field(default=Decimal("0"), ge=0)
    fixed_per_contract: Decimal = Field(default=Decimal("0"), ge=0)


class LifecycleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="explicit_options_lifecycle", min_length=1, max_length=80)
    exercise_enabled: bool = True
    assignment_enabled: bool = True
    expiry_enabled: bool = True
    corporate_actions_enabled: bool = True
    market_cutoff: str = "16:00 America/New_York"
    contract_multiplier: int = Field(default=100, ge=1)


class InitialStockLot(BaseModel):
    """Explicit stock inventory required before a covered-call backtest."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=32)
    quantity: Decimal = Field(gt=0)
    acquisition_price: Decimal = Field(gt=0)
    acquisition_fee: Decimal = Field(default=Decimal("0"), ge=0)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class BacktestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1, max_length=36)
    strategy: BacktestStrategy
    symbols: list[str] = Field(min_length=1, max_length=20)
    start_date: date = BACKTEST_DEFAULT_START
    end_date: date = BACKTEST_DEFAULT_END
    initial_cash: Decimal = Field(default=Decimal("100000"), gt=0)
    parameters: dict[str, Any] = Field(default_factory=dict)
    fee_model: FeeModel
    slippage_model: SlippageModel
    lifecycle_model: LifecycleModel = Field(default_factory=LifecycleModel)
    initial_stock_lots: list[InitialStockLot] = Field(default_factory=list, max_length=20)
    period_segment: Literal["development", "validation", "holdout", "composite"] = "composite"
    freeze_source_run_id: str | None = Field(default=None, max_length=36)
    formal: bool = True
    idempotency_key: str | None = Field(default=None, max_length=128)
    research_only: bool = False

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            symbol = value.strip().upper()
            if symbol and symbol not in result:
                result.append(symbol)
        if not result:
            raise ValueError("at least one symbol is required")
        return result

    @model_validator(mode="after")
    def validate_request(self) -> "BacktestCreate":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.formal and self.fee_model is None:
            raise ValueError("formal backtests require a fee_model")
        if self.strategy is BacktestStrategy.ZERO_DTE and not self.research_only:
            raise ValueError("zero_dte backtests are research-only")
        if self.strategy is BacktestStrategy.COVERED_CALL and self.formal and not self.initial_stock_lots:
            raise ValueError("formal covered_call backtests require explicit initial_stock_lots")
        if self.initial_stock_lots:
            symbols = set(self.symbols)
            outside = sorted({lot.symbol for lot in self.initial_stock_lots} - symbols)
            if outside:
                raise ValueError("initial_stock_lots contain symbols outside the requested universe: " + ", ".join(outside))
        spans_holdout = self.end_date >= date(2025, 1, 1)
        if self.period_segment == "holdout" and not self.freeze_source_run_id:
            raise ValueError("holdout backtests require freeze_source_run_id")
        if self.formal and spans_holdout and not self.freeze_source_run_id:
            raise ValueError("formal runs covering the holdout period require freeze_source_run_id")
        if self.period_segment not in {"holdout", "composite"} and self.freeze_source_run_id:
            raise ValueError("freeze_source_run_id is only valid for holdout or composite runs")
        return self


class BacktestTrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    timestamp: datetime
    strategy: BacktestStrategy
    symbol: str
    status: str
    legs: list[dict[str, Any]] = Field(default_factory=list)
    gross_pnl: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    net_pnl: Decimal = Decimal("0")
    warnings: list[str] = Field(default_factory=list)


class BacktestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    semantic_hash: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    trades: list[BacktestTrade] = Field(default_factory=list)
    equity_curve: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    raw_payload: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BacktestRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    dataset_id: str
    strategy: BacktestStrategy
    symbols: list[str]
    start_date: date
    end_date: date
    initial_cash: Decimal
    state: BacktestState
    parameters: dict[str, Any] = Field(default_factory=dict)
    fee_model: FeeModel
    slippage_model: SlippageModel
    lifecycle_model: LifecycleModel
    run_manifest: dict[str, Any]
    code_version: str
    engine_version: str
    engine_image_digest: str
    data_hash: str | None = None
    process_identity: dict[str, Any] | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    cancel_requested: bool = False
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result: BacktestResult | None = None
    created_at: datetime
    updated_at: datetime
    idempotent_replayed: bool = False


class BacktestCompareRequest(BaseModel):
    run_ids: list[str] = Field(min_length=2, max_length=20)


class BacktestComparison(BaseModel):
    run_ids: list[str]
    rows: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def canonical_json(value: Any) -> str:
    """Serialize nested model data deterministically for evidence hashes."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def semantic_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def manifest_semantic_hash(manifest: DatasetManifest) -> str:
    """Hash observed manifest content without the capture timestamp."""

    payload = manifest.model_dump(mode="json", exclude={"generated_at"}, exclude_none=True)
    return semantic_hash(payload)


def result_semantic_payload(result: BacktestResult | dict[str, Any]) -> dict[str, Any]:
    """Return only deterministic result fields for repeated-run comparison."""

    if isinstance(result, BaseModel):
        payload = result.model_dump(mode="json")
    else:
        payload = dict(result)
    trades = []
    for trade in payload.get("trades", []) or []:
        item = dict(trade)
        item.pop("id", None)
        trades.append(item)
    events = payload.get("events", []) or []
    if isinstance(events, list):
        events = sorted(events, key=canonical_json)
    return {
        "metrics": payload.get("metrics", {}),
        "trades": trades,
        "equity_curve": payload.get("equity_curve", []),
        "events": events,
        "warnings": sorted(payload.get("warnings", []) or []),
    }
