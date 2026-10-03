"""Durable research screen/case and complete event-timeline routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stocks_tool.api.dependencies import get_research_workspace_service
from stocks_tool.application.services.research_records import ResearchRecordsService
from stocks_tool.application.services.research_workspace import (
    ResearchUniverseLimitError,
    ResearchWatchlistNotFoundError,
    ResearchWorkspaceService,
)
from stocks_tool.adapters.brokers.longbridge import LongbridgeIntegrationError
from stocks_tool.db.session import get_db_session as _get_db_session
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.research_records import (
    DEFAULT_RESEARCH_ACCOUNT_ID,
    CopyResearchScreenRequest,
    CreateResearchScreenRequest,
    ResearchAccountNotFoundError,
    ResearchCase,
    ResearchCaseCaptureRequest,
    ResearchCaptureConfigurationError,
    ResearchCaptureUnavailableError,
    ResearchReferenceError,
    ResearchRecordNotFoundError,
    ResearchScreen,
    ResearchScreenNameConflictError,
    ResearchScopeError,
    ResearchTimelinePage,
    ResearchScreenPage,
    ResearchCasePage,
    UpdateResearchScreenRequest,
)
from stocks_tool.repositories.sqlalchemy_market_event_repository import SQLAlchemyMarketEventRepository
from stocks_tool.repositories.sqlalchemy_pre_open_assessment_run_repository import (
    SQLAlchemyPreOpenAssessmentRunRepository,
)
from stocks_tool.repositories.sqlalchemy_research_repository import SQLAlchemyResearchRepository


router = APIRouter(prefix="/research", tags=["research-records"])


def _workspace_snapshot_provider(workspace: ResearchWorkspaceService):
    def provider(*, screen: ResearchScreen, external_account_id: str, mode: ExecutionMode):
        configured_watchlist_id = screen.configuration.get("watchlist_id")
        warnings: list[str] = []
        captured_at = datetime.now(timezone.utc)
        configured_selected_symbol = screen.configuration.get("selected_symbol")
        selected_symbol = (
            str(configured_selected_symbol).strip().upper()
            if configured_selected_symbol
            else None
        )
        if not selected_symbol:
            raise ResearchCaptureConfigurationError(
                "selected_symbol",
                configured_selected_symbol,
                "Research capture requires a selected_symbol in the current configuration.",
            )
        configured_range = screen.configuration.get("history_range", "3m")
        if not isinstance(configured_range, str) or configured_range not in {"3m", "6m", "1y"}:
            raise ResearchCaptureConfigurationError(
                "history_range",
                configured_range,
                "history_range must be one of 3m, 6m, or 1y.",
            )
        selected_history_range = configured_range
        universe_symbols: set[str] | None = None
        try:
            universe = workspace.get_universe(
                external_account_id=external_account_id,
                watchlist_id=configured_watchlist_id if isinstance(configured_watchlist_id, str) else None,
                mode=mode,
            )
            universe_payload = universe.model_dump(mode="json")
            captured_at = universe.generated_at
            warnings.extend(universe.warnings)
            universe_symbols = {
                str(row.symbol).strip().upper()
                for row in universe.rows
                if str(row.symbol).strip()
            }
            selected_symbols = list(screen.symbols) or sorted(universe_symbols)
        except (ResearchWatchlistNotFoundError, ResearchUniverseLimitError):
            raise
        except (LongbridgeIntegrationError, TimeoutError, ConnectionError):
            # A case records the fact that a capture was attempted even when a
            # read dependency is unavailable.  The warning is the evidence;
            # the exception is intentionally not promoted into broker state.
            universe_payload = {}
            selected_symbols = list(screen.symbols)
            warnings.append("research_universe_unavailable")

        selected_symbols = [str(symbol).strip().upper() for symbol in selected_symbols if str(symbol).strip()]
        selected_symbols = list(dict.fromkeys(selected_symbols))
        if selected_symbol not in selected_symbols or (
            universe_symbols is not None and selected_symbol not in universe_symbols
        ):
            raise ResearchCaptureConfigurationError(
                "selected_symbol",
                selected_symbol,
                "selected_symbol must be present in the captured research universe.",
            )
        primary_symbol = selected_symbol

        # Capture the selected symbol's technical evidence only.  The case
        # records explicit primary-only coverage instead of claiming that a
        # 50-symbol screen has complete technical evidence.
        technical_symbols = [primary_symbol] if primary_symbol else []
        try:
            technicals = workspace.get_technicals(symbols=technical_symbols, mode=mode)
            technicals_payload = technicals.model_dump(mode="json")
            technicals_warnings = [
                result.warning
                for result in technicals.results
                if result.warning
            ]
            warnings.extend(technicals_warnings)
        except (LongbridgeIntegrationError, TimeoutError, ConnectionError):
            technicals_payload = {"mode": mode.value, "results": []}
            warnings.append("research_technicals_unavailable")

        # The selected primary symbol is the chart evidence.  The full
        # universe and coverage metadata remain available in the case; we do
        # not fetch a history chart for every row.
        history_payload: dict[str, object] = {}
        if primary_symbol:
            try:
                history = workspace.get_history(
                    symbol=primary_symbol,
                    range_name=selected_history_range,
                    mode=mode,
                )
                history_payload = history.model_dump(mode="json")
                warnings.extend(history.warnings)
            except (LongbridgeIntegrationError, TimeoutError, ConnectionError):
                warnings.append("research_history_unavailable")

        if len(selected_symbols) > 1:
            warnings.append("technical_coverage_primary_only")
        unique_warnings = list(dict.fromkeys(warning for warning in warnings if warning))
        data_quality = universe_payload.get("data_quality", "unavailable")
        if unique_warnings and data_quality == "live":
            data_quality = "partial"
        technical_coverage = {
            "requested_symbols": [primary_symbol] if primary_symbol else [],
            "covered_symbols": [
                result.get("symbol")
                for result in technicals_payload.get("results", [])
                if isinstance(result, dict) and result.get("status") in {"ok", "partial"}
            ],
            "complete": bool(primary_symbol)
            and len(selected_symbols) <= 1
            and not any(
                warning in unique_warnings
                for warning in {"research_technicals_unavailable"}
            ),
            "scope": "primary_symbol_only",
        }
        return {
            "configuration": dict(screen.configuration),
            "universe": {
                "research_universe": universe_payload,
                "technicals": technicals_payload,
                "history": history_payload,
                "technical_coverage": technical_coverage,
            },
            "symbols": selected_symbols[:50],
            "primary_symbol": primary_symbol,
            "as_of": captured_at,
            "data_quality": data_quality,
            "warnings": unique_warnings,
            "source": "research_workspace_capture",
        }

    return provider


def get_research_record_service(
    session: Session = Depends(_get_db_session),
    workspace: ResearchWorkspaceService = Depends(get_research_workspace_service),
) -> ResearchRecordsService:
    """Build the service; the workspace is only called during explicit capture."""

    return ResearchRecordsService(
        repository=SQLAlchemyResearchRepository(session),
        market_events=SQLAlchemyMarketEventRepository(session),
        pre_open_runs=SQLAlchemyPreOpenAssessmentRunRepository(session),
        snapshot_provider=_workspace_snapshot_provider(workspace),
    )


def _mode(value: Literal["paper", "live"]) -> ExecutionMode:
    return ExecutionMode(value)


def _raise_record_error(exc: Exception) -> None:
    if isinstance(exc, ResearchAccountNotFoundError):
        raise HTTPException(
            status_code=404,
            detail={"code": "research_account_not_found", "external_account_id": exc.external_account_id},
        ) from exc
    if isinstance(exc, ResearchRecordNotFoundError):
        raise HTTPException(
            status_code=404,
            detail={"code": f"research_{exc.record_type}_not_found", "id": exc.record_id},
        ) from exc
    if isinstance(exc, ResearchScopeError):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "research_scope_mismatch",
                "record_type": exc.record_type,
                "id": exc.record_id,
                "external_account_id": exc.account_id,
                "mode": exc.mode.value,
            },
        ) from exc
    if isinstance(exc, ResearchReferenceError):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "research_reference_scope_invalid",
                "reference_type": exc.reference_type,
                "missing_ids": exc.missing_ids,
            },
        ) from exc
    if isinstance(exc, ResearchScreenNameConflictError):
        raise HTTPException(
            status_code=409,
            detail={"code": "research_screen_name_conflict", "name": exc.name},
        ) from exc
    if isinstance(exc, ResearchCaptureUnavailableError):
        raise HTTPException(
            status_code=503,
            detail={"code": "research_capture_unavailable", "message": str(exc)},
        ) from exc
    if isinstance(exc, ResearchCaptureConfigurationError):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "research_capture_configuration_invalid",
                "field": exc.field,
                "message": exc.message,
            },
        ) from exc
    if isinstance(exc, ResearchWatchlistNotFoundError):
        raise HTTPException(
            status_code=404,
            detail={"code": "research_watchlist_not_found"},
        ) from exc
    if isinstance(exc, ResearchUniverseLimitError):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "research_universe_limit_exceeded",
                "limit": 50,
                "count": exc.count,
            },
        ) from exc
    raise exc


@router.post("/screens", response_model=ResearchScreen, status_code=status.HTTP_201_CREATED)
def create_research_screen(
    request: CreateResearchScreenRequest,
    service: ResearchRecordsService = Depends(get_research_record_service),
) -> ResearchScreen:
    try:
        return service.create_screen(request)
    except Exception as exc:
        _raise_record_error(exc)
        raise  # pragma: no cover


@router.get("/screens", response_model=ResearchScreenPage)
def list_research_screens(
    external_account_id: str = Query(default=DEFAULT_RESEARCH_ACCOUNT_ID, max_length=64),
    mode: Literal["paper", "live"] = Query(default="paper"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=4096),
    service: ResearchRecordsService = Depends(get_research_record_service),
) -> ResearchScreenPage:
    try:
        return service.list_screens_page(
            external_account_id=external_account_id,
            mode=_mode(mode),
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "research_screen_cursor_invalid", "message": str(exc)},
        ) from exc


@router.get("/screens/{screen_id}", response_model=ResearchScreen)
def get_research_screen(
    screen_id: str,
    external_account_id: str = Query(default=DEFAULT_RESEARCH_ACCOUNT_ID, max_length=64),
    mode: Literal["paper", "live"] = Query(default="paper"),
    service: ResearchRecordsService = Depends(get_research_record_service),
) -> ResearchScreen:
    try:
        return service.get_screen(screen_id, external_account_id=external_account_id, mode=_mode(mode))
    except Exception as exc:
        _raise_record_error(exc)
        raise  # pragma: no cover


@router.patch("/screens/{screen_id}", response_model=ResearchScreen)
def update_research_screen(
    screen_id: str,
    request: UpdateResearchScreenRequest,
    external_account_id: str = Query(default=DEFAULT_RESEARCH_ACCOUNT_ID, max_length=64),
    mode: Literal["paper", "live"] = Query(default="paper"),
    service: ResearchRecordsService = Depends(get_research_record_service),
) -> ResearchScreen:
    try:
        return service.update_screen(
            screen_id,
            request,
            external_account_id=external_account_id,
            mode=_mode(mode),
        )
    except Exception as exc:
        _raise_record_error(exc)
        raise  # pragma: no cover


@router.post("/screens/{screen_id}/copy", response_model=ResearchScreen, status_code=status.HTTP_201_CREATED)
def copy_research_screen(
    screen_id: str,
    request: CopyResearchScreenRequest | None = None,
    external_account_id: str = Query(default=DEFAULT_RESEARCH_ACCOUNT_ID, max_length=64),
    mode: Literal["paper", "live"] = Query(default="paper"),
    service: ResearchRecordsService = Depends(get_research_record_service),
) -> ResearchScreen:
    try:
        return service.copy_screen(
            screen_id,
            request,
            external_account_id=external_account_id,
            mode=_mode(mode),
        )
    except Exception as exc:
        _raise_record_error(exc)
        raise  # pragma: no cover


@router.post("/cases", response_model=ResearchCase, status_code=status.HTTP_201_CREATED)
def capture_research_case(
    request: ResearchCaseCaptureRequest,
    service: ResearchRecordsService = Depends(get_research_record_service),
) -> ResearchCase:
    try:
        # The service invokes the existing workspace read model here.  No
        # provider call is made by any GET screen/case/timeline route.
        return service.capture_case(request)
    except Exception as exc:
        _raise_record_error(exc)
        raise  # pragma: no cover


@router.get("/cases", response_model=ResearchCasePage)
def list_research_cases(
    external_account_id: str = Query(default=DEFAULT_RESEARCH_ACCOUNT_ID, max_length=64),
    mode: Literal["paper", "live"] = Query(default="paper"),
    screen_id: str | None = Query(default=None, max_length=36),
    symbol: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=4096),
    service: ResearchRecordsService = Depends(get_research_record_service),
) -> ResearchCasePage:
    try:
        return service.list_cases_page(
            external_account_id=external_account_id,
            mode=_mode(mode),
            screen_id=screen_id,
            symbol=symbol,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "research_case_cursor_invalid", "message": str(exc)},
        ) from exc


@router.get("/cases/{case_id}", response_model=ResearchCase)
def get_research_case(
    case_id: str,
    external_account_id: str = Query(default=DEFAULT_RESEARCH_ACCOUNT_ID, max_length=64),
    mode: Literal["paper", "live"] = Query(default="paper"),
    service: ResearchRecordsService = Depends(get_research_record_service),
) -> ResearchCase:
    try:
        return service.get_case(case_id, external_account_id=external_account_id, mode=_mode(mode))
    except Exception as exc:
        _raise_record_error(exc)
        raise  # pragma: no cover


def _range_start(range_name: str, end: datetime) -> datetime:
    normalized = range_name.strip().lower()
    if normalized in {"7d", "7day", "week"}:
        days = 7
    elif normalized in {"90d", "quarter"}:
        days = 90
    elif normalized in {"1y", "1yr", "year", "365d"}:
        days = 365
    elif normalized in {"30d", "30day", "month", ""}:
        days = 30
    else:
        raise HTTPException(
            status_code=422,
            detail={"code": "research_timeline_range_invalid", "range": range_name},
        )
    return end - timedelta(days=days)


def _timeline_symbols(symbol: str | None, symbols: list[str] | None) -> list[str]:
    raw_values = ([symbol] if symbol else []) + (symbols or [])
    values = [part for value in raw_values for part in value.split(",")]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip().upper()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


@router.get("/timeline", response_model=ResearchTimelinePage)
def get_research_event_timeline(
    external_account_id: str = Query(default=DEFAULT_RESEARCH_ACCOUNT_ID, max_length=64),
    mode: Literal["paper", "live"] = Query(default="paper"),
    symbol: str | None = Query(default=None, max_length=32),
    symbols: list[str] | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    range_name: str = Query(default="30d", alias="range"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=4096),
    service: ResearchRecordsService = Depends(get_research_record_service),
) -> ResearchTimelinePage:
    end_value = end or datetime.now(timezone.utc)
    start_value = start or _range_start(range_name, end_value)
    try:
        return service.get_event_timeline_page(
            external_account_id=external_account_id,
            mode=_mode(mode),
            start=start_value,
            end=end_value,
            symbols=_timeline_symbols(symbol, symbols),
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "research_timeline_invalid", "message": str(exc)}) from exc
