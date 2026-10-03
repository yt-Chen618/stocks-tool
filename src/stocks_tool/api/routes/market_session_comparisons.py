"""Read-only market-session comparison capture and read routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from stocks_tool.api.dependencies import get_longbridge_adapter
from stocks_tool.db.session import get_db_session
from stocks_tool.application.services.market_session_comparison import (
    MarketSessionComparisonService,
)
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.pagination import CursorError
from stocks_tool.domain.market_session_comparisons import (
    CaptureMarketSessionComparisonRequest,
    CaptureMarketSessionComparisonResult,
    MarketSessionComparison,
    MarketSessionComparisonAccountNotFoundError,
    MarketSessionComparisonConfigurationError,
    MarketSessionComparisonIdempotencyConflictError,
    MarketSessionComparisonNotFoundError,
    MarketSessionComparisonPage,
    MarketSessionComparisonScopeError,
)
from stocks_tool.repositories.sqlalchemy_market_session_repository import (
    SQLAlchemyMarketSessionComparisonRepository,
)
from stocks_tool.repositories.sqlalchemy_pre_open_assessment_run_repository import (
    SQLAlchemyPreOpenAssessmentRunRepository,
)
from stocks_tool.ports.broker_gateway import BrokerMarketDataGateway


router = APIRouter(prefix="/market-session-comparisons", tags=["market-session-comparisons"])


def get_market_session_comparison_service(
    session: Session = Depends(get_db_session),
    adapter: BrokerMarketDataGateway = Depends(get_longbridge_adapter),
) -> MarketSessionComparisonService:
    return MarketSessionComparisonService(
        comparisons=SQLAlchemyMarketSessionComparisonRepository(session),
        pre_open_runs=SQLAlchemyPreOpenAssessmentRunRepository(session),
        market_data=adapter,
    )


def _execution_mode(value: Literal["paper", "live"]) -> ExecutionMode:
    return ExecutionMode(value)


def _raise_comparison_error(exc: Exception) -> None:
    if isinstance(exc, MarketSessionComparisonAccountNotFoundError):
        raise HTTPException(
            status_code=404,
            detail={"code": "market_session_comparison_account_not_found", "external_account_id": exc.external_account_id},
        ) from exc
    if isinstance(exc, MarketSessionComparisonNotFoundError):
        raise HTTPException(
            status_code=404,
            detail={"code": "market_session_comparison_not_found", "id": exc.comparison_id},
        ) from exc
    if isinstance(exc, MarketSessionComparisonScopeError):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "market_session_comparison_scope_mismatch",
                "id": exc.comparison_id,
                "external_account_id": exc.external_account_id,
                "mode": exc.mode.value,
            },
        ) from exc
    if isinstance(exc, MarketSessionComparisonConfigurationError):
        raise HTTPException(
            status_code=422,
            detail={"code": "market_session_comparison_configuration_invalid", "field": exc.field, "message": exc.message},
        ) from exc
    if isinstance(exc, MarketSessionComparisonIdempotencyConflictError):
        raise HTTPException(
            status_code=409,
            detail={"code": "market_session_comparison_idempotency_conflict", "capture_key": exc.capture_key},
        ) from exc
    raise exc


@router.post("", response_model=CaptureMarketSessionComparisonResult, status_code=status.HTTP_201_CREATED)
def capture_market_session_comparison(
    request: CaptureMarketSessionComparisonRequest,
    response: Response,
    service: MarketSessionComparisonService = Depends(get_market_session_comparison_service),
) -> CaptureMarketSessionComparisonResult:
    try:
        result = service.capture(request)
    except Exception as exc:
        _raise_comparison_error(exc)
        raise  # pragma: no cover
    if result.duplicate:
        response.status_code = status.HTTP_200_OK
    return result


@router.get("", response_model=MarketSessionComparisonPage)
def list_market_session_comparisons(
    external_account_id: str = Query(default="LBPT10087357", max_length=64),
    mode: Literal["paper", "live"] = Query(default="paper"),
    symbol: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=4096),
    service: MarketSessionComparisonService = Depends(get_market_session_comparison_service),
) -> MarketSessionComparisonPage:
    try:
        return service.list(
            external_account_id=external_account_id,
            mode=_execution_mode(mode),
            symbol=symbol,
            limit=limit,
            cursor=cursor,
        )
    except Exception as exc:
        if isinstance(exc, CursorError):
            raise HTTPException(
                status_code=422,
                detail={"code": "market_session_comparison_cursor_invalid", "message": str(exc)},
            ) from exc
        _raise_comparison_error(exc)
        raise  # pragma: no cover


@router.get("/latest", response_model=MarketSessionComparison)
def get_latest_market_session_comparison(
    symbol: str = Query(..., min_length=1, max_length=32),
    external_account_id: str = Query(default="LBPT10087357", max_length=64),
    mode: Literal["paper", "live"] = Query(default="paper"),
    service: MarketSessionComparisonService = Depends(get_market_session_comparison_service),
) -> MarketSessionComparison:
    try:
        return service.latest(
            external_account_id=external_account_id,
            mode=_execution_mode(mode),
            symbol=symbol,
        )
    except Exception as exc:
        _raise_comparison_error(exc)
        raise  # pragma: no cover


@router.get("/{comparison_id}", response_model=MarketSessionComparison)
def get_market_session_comparison(
    comparison_id: str,
    external_account_id: str = Query(default="LBPT10087357", max_length=64),
    mode: Literal["paper", "live"] = Query(default="paper"),
    service: MarketSessionComparisonService = Depends(get_market_session_comparison_service),
) -> MarketSessionComparison:
    try:
        return service.get(
            comparison_id,
            external_account_id=external_account_id,
            mode=_execution_mode(mode),
        )
    except Exception as exc:
        _raise_comparison_error(exc)
        raise  # pragma: no cover
