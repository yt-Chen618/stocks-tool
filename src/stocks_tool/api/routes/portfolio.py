from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from stocks_tool.application.services.portfolio import (
    DEFAULT_MAX_POINTS,
    EVIDENCE_ID_LIMIT,
    PortfolioAnalytics,
    PortfolioAnalyticsService,
    PortfolioRisk,
)
from stocks_tool.db.session import get_db_session
from stocks_tool.domain.enums import ExecutionMode

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def get_portfolio_service(
    session: Session = Depends(get_db_session),
) -> PortfolioAnalyticsService:
    return PortfolioAnalyticsService(session)


@router.get("/analytics", response_model=PortfolioAnalytics)
def get_portfolio_analytics(
    external_account_id: str = Query(..., min_length=1, max_length=64),
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    max_points: int = Query(default=DEFAULT_MAX_POINTS, ge=1, le=2_000),
    service: PortfolioAnalyticsService = Depends(get_portfolio_service),
) -> PortfolioAnalytics:
    try:
        return service.get_analytics(
            external_account_id=external_account_id,
            mode=mode,
            start=start,
            end=end,
            max_points=max_points,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "portfolio_query_invalid", "message": str(exc)}) from exc


@router.get("/risk", response_model=PortfolioRisk)
def get_portfolio_risk(
    external_account_id: str = Query(..., min_length=1, max_length=64),
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    as_of: datetime | None = Query(default=None),
    max_items: int = Query(default=EVIDENCE_ID_LIMIT, ge=1, le=EVIDENCE_ID_LIMIT),
    service: PortfolioAnalyticsService = Depends(get_portfolio_service),
) -> PortfolioRisk:
    try:
        return service.get_risk(
            external_account_id=external_account_id,
            mode=mode,
            as_of=as_of,
            max_items=max_items,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "portfolio_query_invalid", "message": str(exc)}) from exc
