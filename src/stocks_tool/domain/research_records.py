"""Durable research screen and point-in-time research case contracts.

These models intentionally live beside the older ``domain.models`` module.  The
research records are a separate bounded context and are not used as order
authorization evidence.  A case is an immutable explanation of what the
research desk saw at a particular time; subsequent quote, position, or event
updates must not rewrite it.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from stocks_tool.domain.enums import ExecutionMode, MarketEventSeverity, MarketEventType
from stocks_tool.domain.models import MarketEvent
from stocks_tool.domain.pagination import CursorPage


DEFAULT_RESEARCH_ACCOUNT_ID = "LBPT10087357"
MAX_RESEARCH_SCREEN_SYMBOLS = 50


class ResearchRecordError(ValueError):
    """Base error for user-correctable research-record requests."""


class ResearchAccountNotFoundError(ResearchRecordError):
    def __init__(self, external_account_id: str) -> None:
        self.external_account_id = external_account_id
        super().__init__(f"No local broker account was found for '{external_account_id}'.")


class ResearchRecordNotFoundError(ResearchRecordError):
    def __init__(self, record_type: str, record_id: str) -> None:
        self.record_type = record_type
        self.record_id = record_id
        super().__init__(f"Research {record_type} '{record_id}' was not found.")


class ResearchScopeError(ResearchRecordError):
    def __init__(self, record_type: str, record_id: str, account_id: str, mode: ExecutionMode) -> None:
        self.record_type = record_type
        self.record_id = record_id
        self.account_id = account_id
        self.mode = mode
        super().__init__(
            f"Research {record_type} '{record_id}' belongs to a different account or execution mode."
        )


class ResearchReferenceError(ResearchRecordError):
    def __init__(self, reference_type: str, missing_ids: list[str]) -> None:
        self.reference_type = reference_type
        self.missing_ids = missing_ids
        joined = ", ".join(missing_ids)
        super().__init__(f"Some {reference_type} references are missing or outside this account/mode: {joined}.")


class ResearchScreenNameConflictError(ResearchRecordError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"A research screen named '{name}' already exists for this account and mode.")


class ResearchCaptureUnavailableError(ResearchRecordError):
    pass


class ResearchCaptureConfigurationError(ResearchRecordError):
    def __init__(self, field: str, value: object, message: str) -> None:
        self.field = field
        self.value = value
        self.message = message
        super().__init__(message)


def _normalize_account(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("external_account_id must not be blank")
    return normalized


def _normalize_symbols(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        symbol = value.strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    if len(normalized) > MAX_RESEARCH_SCREEN_SYMBOLS:
        raise ValueError(
            f"symbols must contain at most {MAX_RESEARCH_SCREEN_SYMBOLS} unique symbols"
        )
    return normalized


class ResearchScreen(BaseModel):
    """A mutable, named research configuration scoped to one account/mode."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    external_account_id: str = Field(default=DEFAULT_RESEARCH_ACCOUNT_ID, min_length=1, max_length=64)
    mode: ExecutionMode = ExecutionMode.PAPER
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    configuration: dict[str, Any] = Field(default_factory=dict)
    symbols: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("external_account_id")
    @classmethod
    def validate_account(cls, value: str) -> str:
        return _normalize_account(value)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("symbols")
    @classmethod
    def normalize_screen_symbols(cls, value: list[str]) -> list[str]:
        return _normalize_symbols(value)


class CreateResearchScreenRequest(BaseModel):
    external_account_id: str = Field(default=DEFAULT_RESEARCH_ACCOUNT_ID, min_length=1, max_length=64)
    mode: ExecutionMode = ExecutionMode.PAPER
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    configuration: dict[str, Any] = Field(default_factory=dict)
    symbols: list[str] = Field(default_factory=list)

    @field_validator("external_account_id")
    @classmethod
    def validate_account(cls, value: str) -> str:
        return _normalize_account(value)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("symbols")
    @classmethod
    def normalize_screen_symbols(cls, value: list[str]) -> list[str]:
        return _normalize_symbols(value)


class UpdateResearchScreenRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    configuration: dict[str, Any] | None = None
    symbols: list[str] | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("symbols")
    @classmethod
    def normalize_screen_symbols(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _normalize_symbols(value)


class CopyResearchScreenRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    external_account_id: str | None = Field(default=None, min_length=1, max_length=64)
    mode: ExecutionMode | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("external_account_id")
    @classmethod
    def normalize_copy_account(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_account(value)


class ResearchSnapshot(BaseModel):
    """The server-produced payload frozen into a research case."""

    configuration: dict[str, Any] = Field(default_factory=dict)
    universe: dict[str, Any] | list[Any] = Field(default_factory=dict)
    symbols: list[str] = Field(default_factory=list)
    primary_symbol: str | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data_quality: str = Field(default="unknown", min_length=1, max_length=32)
    warnings: list[str] = Field(default_factory=list)
    source: str = Field(default="research_workspace", min_length=1, max_length=64)

    @field_validator("symbols")
    @classmethod
    def normalize_snapshot_symbols(cls, value: list[str]) -> list[str]:
        return _normalize_symbols(value)

    @field_validator("primary_symbol")
    @classmethod
    def normalize_primary_symbol(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None

    @field_validator("as_of")
    @classmethod
    def normalize_as_of(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    @field_validator("warnings")
    @classmethod
    def normalize_warnings(cls, value: list[str]) -> list[str]:
        return [warning.strip() for warning in value if warning.strip()]


class ResearchCaseCaptureRequest(BaseModel):
    screen_id: str = Field(min_length=1, max_length=36)
    external_account_id: str | None = Field(default=None, min_length=1, max_length=64)
    mode: ExecutionMode | None = None
    # The current UI state may differ from the last saved named screen.  This
    # is a validated configuration override only; it is never broker evidence.
    configuration: dict[str, Any] | None = None
    symbols: list[str] | None = None
    title: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)
    next_action: str | None = Field(default=None, max_length=1000)
    proposal_ids: list[str] = Field(default_factory=list, max_length=50)
    advisor_run_ids: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("external_account_id")
    @classmethod
    def normalize_request_account(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_account(value)

    @field_validator("symbols")
    @classmethod
    def normalize_capture_symbols(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _normalize_symbols(value)

    @field_validator("title", "notes", "next_action")
    @classmethod
    def normalize_case_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("proposal_ids", "advisor_run_ids")
    @classmethod
    def normalize_reference_ids(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = value.strip()
            if item and item not in seen:
                seen.add(item)
                normalized.append(item)
        return normalized


class ResearchCase(BaseModel):
    """An immutable point-in-time research snapshot."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    screen_id: str | None = None
    external_account_id: str = Field(default=DEFAULT_RESEARCH_ACCOUNT_ID, min_length=1, max_length=64)
    mode: ExecutionMode = ExecutionMode.PAPER
    title: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)
    next_action: str | None = Field(default=None, max_length=1000)
    configuration: dict[str, Any] = Field(default_factory=dict)
    universe: dict[str, Any] | list[Any] = Field(default_factory=dict)
    symbols: list[str] = Field(default_factory=list)
    primary_symbol: str | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data_quality: str = Field(default="unknown", min_length=1, max_length=32)
    warnings: list[str] = Field(default_factory=list)
    source: str = Field(default="research_workspace", min_length=1, max_length=64)
    proposal_ids: list[str] = Field(default_factory=list)
    advisor_run_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("external_account_id")
    @classmethod
    def validate_account(cls, value: str) -> str:
        return _normalize_account(value)

    @field_validator("symbols")
    @classmethod
    def normalize_case_symbols(cls, value: list[str]) -> list[str]:
        return _normalize_symbols(value)

    @field_validator("primary_symbol")
    @classmethod
    def normalize_case_primary_symbol(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None

    @field_validator("title", "notes", "next_action")
    @classmethod
    def normalize_case_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("as_of", "created_at")
    @classmethod
    def normalize_case_timestamps(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class ResearchTimelinePreOpenLink(BaseModel):
    kind: Literal["pre_open"] = "pre_open"
    run_id: str
    external_account_id: str
    target_session_date: date
    scheduled_at: datetime
    preferred_vehicle: str | None = None
    summary: str | None = None
    review_status: str
    source: str = "pre_open_assessment"


class ResearchTimelineItem(BaseModel):
    kind: Literal["market_event", "pre_open"]
    scheduled_at: datetime
    symbol: str | None = None
    title: str
    source: str | None = None
    severity: MarketEventSeverity | None = None
    event_type: MarketEventType | None = None
    event_id: str | None = None
    pre_open_run_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ResearchTimelineResponse(BaseModel):
    external_account_id: str = DEFAULT_RESEARCH_ACCOUNT_ID
    mode: ExecutionMode = ExecutionMode.PAPER
    start: datetime
    end: datetime
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    symbols: list[str] = Field(default_factory=list)
    events: list[MarketEvent] = Field(default_factory=list)
    pre_open_links: list[ResearchTimelinePreOpenLink] = Field(default_factory=list)
    items: list[ResearchTimelineItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ResearchScreenPage(CursorPage[ResearchScreen]):
    """Bounded keyset page for the new durable-screen read contract."""


class ResearchCasePage(CursorPage[ResearchCase]):
    """Bounded keyset page for immutable research cases."""


class ResearchTimelinePage(ResearchTimelineResponse):
    """Bounded timeline page; ``items`` is the complete page, not a display cap."""

    next_cursor: str | None = None
    has_more: bool = False
    limit: int = Field(default=50, ge=1, le=100)
