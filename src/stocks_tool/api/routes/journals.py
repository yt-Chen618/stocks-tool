from fastapi import APIRouter, Depends, HTTPException, Query, status

from stocks_tool.api.dependencies import get_journal_repository, get_journal_service
from stocks_tool.application.services.journal import JournalService
from stocks_tool.domain.enums import JournalEntryType
from stocks_tool.domain.models import CreateJournalEntryRequest, JournalEntry
from stocks_tool.domain.pagination import CursorPage
from stocks_tool.ports.repository import JournalRepository

router = APIRouter(prefix="/journals", tags=["journals"])


@router.get("", response_model=list[JournalEntry])
def list_journal_entries(
    external_account_id: str | None = None,
    order_id: str | None = None,
    trade_plan_id: str | None = None,
    entry_type: JournalEntryType | None = None,
    repository: JournalRepository = Depends(get_journal_repository),
) -> list[JournalEntry]:
    return repository.list_entries(
        external_account_id=external_account_id,
        order_id=order_id,
        trade_plan_id=trade_plan_id,
        entry_type=entry_type,
    )


@router.get("/paged", response_model=CursorPage[JournalEntry])
def list_journal_entries_page(
    external_account_id: str | None = Query(default=None),
    order_id: str | None = Query(default=None),
    trade_plan_id: str | None = Query(default=None),
    entry_type: JournalEntryType | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    repository: JournalRepository = Depends(get_journal_repository),
) -> CursorPage[JournalEntry]:
    try:
        return repository.list_entries_page(
            external_account_id=external_account_id,
            order_id=order_id,
            trade_plan_id=trade_plan_id,
            entry_type=entry_type,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("", response_model=JournalEntry, status_code=status.HTTP_201_CREATED)
def create_journal_entry(
    request: CreateJournalEntryRequest,
    service: JournalService = Depends(get_journal_service),
) -> JournalEntry:
    try:
        return service.create_entry(request)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
