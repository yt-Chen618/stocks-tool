from fastapi import APIRouter, Depends, HTTPException, Response

from stocks_tool.api.dependencies import get_watchlist_repository
from stocks_tool.domain.models import (
    AddWatchlistItemRequest,
    CreateWatchlistRequest,
    UpdateWatchlistItemRequest,
    UpdateWatchlistRequest,
    Watchlist,
)
from stocks_tool.ports.repository import WatchlistItemConflictError, WatchlistRepository

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
    if not request.name.strip():
        raise HTTPException(status_code=422, detail="Watchlist name cannot be blank.")
    return repository.create_watchlist(request)


@router.post("/{watchlist_id}/items", response_model=Watchlist)
def add_watchlist_item(
    watchlist_id: str,
    request: AddWatchlistItemRequest,
    repository: WatchlistRepository = Depends(get_watchlist_repository),
) -> Watchlist:
    try:
        watchlist = repository.add_item(watchlist_id, request)
    except WatchlistItemConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found.")
    return watchlist


@router.patch("/{watchlist_id}", response_model=Watchlist)
def update_watchlist(
    watchlist_id: str,
    request: UpdateWatchlistRequest,
    repository: WatchlistRepository = Depends(get_watchlist_repository),
) -> Watchlist:
    if not request.model_fields_set:
        raise HTTPException(status_code=422, detail="At least one watchlist field is required.")
    if "name" in request.model_fields_set and (
        request.name is None or not request.name.strip()
    ):
        raise HTTPException(status_code=422, detail="Watchlist name cannot be blank.")
    if "is_default" in request.model_fields_set and request.is_default is None:
        raise HTTPException(status_code=422, detail="Watchlist default flag cannot be null.")
    watchlist = repository.update_watchlist(watchlist_id, request)
    if watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found.")
    return watchlist


@router.patch("/{watchlist_id}/items/{item_id}", response_model=Watchlist)
def update_watchlist_item(
    watchlist_id: str,
    item_id: str,
    request: UpdateWatchlistItemRequest,
    repository: WatchlistRepository = Depends(get_watchlist_repository),
) -> Watchlist:
    watchlist = repository.update_item(watchlist_id, item_id, request)
    if watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found.")
    return watchlist


@router.delete("/{watchlist_id}/items/{item_id}", status_code=204)
def delete_watchlist_item(
    watchlist_id: str,
    item_id: str,
    repository: WatchlistRepository = Depends(get_watchlist_repository),
) -> Response:
    if not repository.delete_item(watchlist_id, item_id):
        raise HTTPException(status_code=404, detail="Watchlist item not found.")
    return Response(status_code=204)
