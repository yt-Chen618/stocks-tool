from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from stocks_tool.api.dependencies import get_research_service, get_research_workspace_service
from stocks_tool.application.services.research import ResearchService
from stocks_tool.application.services.research_workspace import (
    RESEARCH_TECHNICALS_LIMIT,
    RESEARCH_UNIVERSE_LIMIT,
    ResearchUniverseLimitError,
    ResearchWatchlistNotFoundError,
    ResearchWorkspaceService,
)
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import (
    CandidateScore,
    ResearchHistoryResponse,
    ResearchRankingRequest,
    ResearchTechnicalsResponse,
    ResearchUniverseResponse,
)

router = APIRouter(prefix="/research", tags=["research"])


@router.post("/rank", response_model=list[CandidateScore])
def rank_candidates(
    request: ResearchRankingRequest,
    research_service: ResearchService = Depends(get_research_service),
) -> list[CandidateScore]:
    return research_service.rank_candidates(request.candidates)


@router.get("/universe", response_model=ResearchUniverseResponse)
def get_research_universe(
    external_account_id: str | None = Query(default=None, max_length=64),
    watchlist_id: str | None = Query(default=None, max_length=36),
    mode: Literal["paper"] = "paper",
    service: ResearchWorkspaceService = Depends(get_research_workspace_service),
) -> ResearchUniverseResponse:
    try:
        return service.get_universe(
            external_account_id=external_account_id,
            watchlist_id=watchlist_id,
            mode=ExecutionMode(mode),
        )
    except ResearchWatchlistNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"code": "research_watchlist_not_found", "watchlist_id": watchlist_id},
        ) from None
    except ResearchUniverseLimitError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "research_universe_limit_exceeded",
                "limit": RESEARCH_UNIVERSE_LIMIT,
                "count": exc.count,
            },
        ) from None


@router.get("/technicals", response_model=ResearchTechnicalsResponse)
def get_research_technicals(
    symbols: list[str] = Query(...),
    mode: Literal["paper"] = "paper",
    service: ResearchWorkspaceService = Depends(get_research_workspace_service),
) -> ResearchTechnicalsResponse:
    expanded_symbols = [
        part.strip()
        for value in symbols
        for part in value.split(",")
        if part.strip()
    ]
    if not expanded_symbols:
        raise HTTPException(
            status_code=422,
            detail={"code": "research_symbols_required"},
        )
    if len(expanded_symbols) > RESEARCH_TECHNICALS_LIMIT:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "research_technicals_limit_exceeded",
                "limit": RESEARCH_TECHNICALS_LIMIT,
                "count": len(expanded_symbols),
            },
        )
    return service.get_technicals(symbols=expanded_symbols, mode=ExecutionMode(mode))


@router.get("/symbols/{symbol}/history", response_model=ResearchHistoryResponse)
def get_research_history(
    symbol: str,
    range_name: Literal["3m", "6m", "1y"] = Query(default="3m", alias="range"),
    mode: Literal["paper"] = "paper",
    service: ResearchWorkspaceService = Depends(get_research_workspace_service),
) -> ResearchHistoryResponse:
    if not symbol.strip() or len(symbol) > 32:
        raise HTTPException(status_code=422, detail={"code": "research_symbol_invalid"})
    return service.get_history(
        symbol=symbol,
        range_name=range_name,
        mode=ExecutionMode(mode),
    )
