from datetime import datetime

from fastapi import APIRouter, Depends, Query

from stocks_tool.api.dependencies import get_market_event_repository
from stocks_tool.domain.enums import MarketEventType
from stocks_tool.domain.models import CreateMarketEventRequest, MarketEvent
from stocks_tool.ports.repository import MarketEventRepository


router = APIRouter(prefix="/market-events", tags=["market-events"])


@router.get("", response_model=list[MarketEvent])
def list_market_events(
    symbol: str | None = Query(default=None),
    event_type: MarketEventType | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    repository: MarketEventRepository = Depends(get_market_event_repository),
) -> list[MarketEvent]:
    return repository.list_events(
        symbol=symbol,
        event_type=event_type,
        start=start,
        end=end,
        limit=limit,
    )


@router.post("", response_model=MarketEvent, status_code=201)
def create_market_event(
    request: CreateMarketEventRequest,
    repository: MarketEventRepository = Depends(get_market_event_repository),
) -> MarketEvent:
    return repository.create_event(request)
