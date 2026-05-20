from fastapi import APIRouter, Depends, HTTPException

from stocks_tool.api.dependencies import get_watchlist_repository
from stocks_tool.domain.models import (
    AddWatchlistItemRequest,
    CreateWatchlistRequest,
    Watchlist,
)
from stocks_tool.ports.repository import WatchlistRepository

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


@router.get("", response_model=list[Watchlist])
def list_watchlists(
    repository: WatchlistRepository = Depends(get_watchlist_repository),
) -> list[Watchlist]:
    return repository.list_watchlists()


@router.post("", response_model=Watchlist, status_code=201)
def create_watchlist(
    request: CreateWatchlistRequest,
    repository: WatchlistRepository = Depends(get_watchlist_repository),
) -> Watchlist:
    return repository.create_watchlist(request)


@router.post("/{watchlist_id}/items", response_model=Watchlist)
def add_watchlist_item(
    watchlist_id: str,
    request: AddWatchlistItemRequest,
    repository: WatchlistRepository = Depends(get_watchlist_repository),
) -> Watchlist:
    watchlist = repository.add_item(watchlist_id, request)
    if watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found.")
    return watchlist

