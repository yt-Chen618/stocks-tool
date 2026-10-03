from fastapi import APIRouter, Depends, HTTPException, Query

from stocks_tool.api.dependencies import get_execution_repository
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import Execution
from stocks_tool.domain.pagination import CursorPage
from stocks_tool.ports.repository import ExecutionRepository

router = APIRouter(prefix="/executions", tags=["executions"])


@router.get("", response_model=list[Execution])
def list_executions(
    external_account_id: str | None = None,
    order_id: str | None = None,
    mode: ExecutionMode | None = Query(default=None),
    repository: ExecutionRepository = Depends(get_execution_repository),
) -> list[Execution]:
    return repository.list_executions(
        external_account_id=external_account_id,
        order_id=order_id,
        mode=mode,
    )


@router.get("/paged", response_model=CursorPage[Execution])
def list_executions_page(
    external_account_id: str | None = Query(default=None),
    order_id: str | None = Query(default=None),
    mode: ExecutionMode | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    repository: ExecutionRepository = Depends(get_execution_repository),
) -> CursorPage[Execution]:
    try:
        return repository.list_executions_page(
            external_account_id=external_account_id,
            order_id=order_id,
            mode=mode,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
