"""Immutable pre-open, regular-close, and after-hours comparison contracts."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.research_records import DEFAULT_RESEARCH_ACCOUNT_ID


class MarketSessionComparisonError(ValueError):
    pass


class MarketSessionComparisonAccountNotFoundError(MarketSessionComparisonError):
    def __init__(self, external_account_id: str) -> None:
        self.external_account_id = external_account_id
        super().__init__(f"No local broker account was found for '{external_account_id}'.")


class MarketSessionComparisonNotFoundError(MarketSessionComparisonError):
    def __init__(self, comparison_id: str) -> None:
        self.comparison_id = comparison_id
        super().__init__(f"Market session comparison '{comparison_id}' was not found.")


class MarketSessionComparisonScopeError(MarketSessionComparisonError):
    def __init__(self, comparison_id: str, external_account_id: str, mode: ExecutionMode) -> None:
        self.comparison_id = comparison_id
        self.external_account_id = external_account_id
        self.mode = mode
        super().__init__(f"Market session comparison '{comparison_id}' belongs to another account or mode.")


class MarketSessionComparisonConfigurationError(MarketSessionComparisonError):
    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(message)


class MarketSessionComparisonIdempotencyConflictError(MarketSessionComparisonError):
    def __init__(self, capture_key: str) -> None:
        self.capture_key = capture_key
        super().__init__(f"Capture key '{capture_key}' was already used with another request scope.")


class MarketSessionEvidence(BaseModel):
    session: Literal["pre_open", "regular_close", "post_market"]
    symbol: str
    price: Decimal | None = None
    timestamp: datetime | None = None
    session_close_at: datetime | None = None
    trading_date: date | None = None
    currency: str | None = None
    source: str
    source_field: str
    raw_payload: dict[str, Any] | None = None

    @field_validator("timestamp", "session_close_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        # A naive timestamp is preserved as unknown evidence.  The service
        # refuses to use it for a verified same-day comparison.
        return value

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol must not be blank")
        return normalized


class CaptureMarketSessionComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_account_id: str = Field(default=DEFAULT_RESEARCH_ACCOUNT_ID, min_length=1, max_length=64)
    mode: ExecutionMode = ExecutionMode.PAPER
    symbol: str = Field(min_length=1, max_length=32)
    pre_open_run_id: str | None = Field(default=None, max_length=36)
    capture_key: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("external_account_id")
    @classmethod
    def normalize_account(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("external_account_id must not be blank")
        return normalized

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol must not be blank")
        return normalized

    @field_validator("pre_open_run_id", "capture_key")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class MarketSessionComparison(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    external_account_id: str = DEFAULT_RESEARCH_ACCOUNT_ID
    mode: ExecutionMode = ExecutionMode.PAPER
    symbol: str
    currency: str | None = None
    account_currency: str | None = None
    quote_currency: str | None = None
    pre_open_run_id: str | None = None
    baseline_session_date: date | None = None
    target_trading_day: date | None = None
    status: Literal["valid", "partial", "not_available"] = "not_available"
    data_quality: Literal["verified", "partial", "unavailable"] = "unavailable"
    reason_codes: list[str] = Field(default_factory=list)
    reason_detail: str = ""
    field_explanations: dict[str, str] = Field(default_factory=dict)
    baseline_price: Decimal | None = None
    regular_close_price: Decimal | None = None
    after_hours_price: Decimal | None = None
    pre_to_regular_close_pct: Decimal | None = None
    regular_close_to_after_hours_pct: Decimal | None = None
    baseline_evidence: MarketSessionEvidence | None = None
    regular_close_evidence: MarketSessionEvidence | None = None
    post_market_evidence: MarketSessionEvidence | None = None
    raw_evidence: dict[str, Any] = Field(default_factory=dict)
    source: str = "longbridge_market_session_capture"
    idempotency_key: str
    evidence_as_of: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol must not be blank")
        return normalized

    @field_validator("evidence_as_of", "created_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return value


class CaptureMarketSessionComparisonResult(BaseModel):
    comparison: MarketSessionComparison
    captured: bool
    duplicate: bool = False
    reason: str | None = None


class MarketSessionComparisonPage(BaseModel):
    items: list[MarketSessionComparison] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=100)
    has_more: bool = False
    next_cursor: str | None = None


DEFAULT_FIELD_EXPLANATIONS = {
    "baseline_price": "盘前基准价来自已保存的 PreOpenAssessmentRun，不使用客户端传入价格。",
    "regular_close_price": "常规收盘参考来自 Longbridge 的交易日收盘字段或同交易日已验证日线收盘，不代表官方收盘竞价成交价。",
    "after_hours_price": "盘后价来自 Longbridge post_market_quote.last_done；缺失时保持为空。",
    "pre_to_regular_close_pct": "从盘前基准价到常规收盘价的变化；任一证据无效时不计算。",
    "regular_close_to_after_hours_pct": "从常规收盘到盘后最后价的变化；无盘后证据时不计算。",
}
